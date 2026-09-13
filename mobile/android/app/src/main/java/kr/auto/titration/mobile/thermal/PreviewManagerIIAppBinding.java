package kr.auto.titration.mobile.thermal;

import android.util.Size;
import androidx.activity.ComponentActivity;
import androidx.lifecycle.Lifecycle;
import com.hik.f2module.F2StreamCallback;
import com.hik.f2module.F2StreamFrame;
import com.hik.f2module.F2UsbModuleHelper;
import com.hik.library.player.d;
import com.hik.viewer.manager.PreviewManagerII;
import com.hik.viewercommon.data.bean.OsdBgCallbackBean;
import com.hik.viewercommon.data.bean.PreviewInfoDataBean;
import com.hik.viewercommon.data.bean.PreviewStreamInfo;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.WeakHashMap;
import java.util.function.BooleanSupplier;
import java.util.function.IntFunction;
import kr.auto.titration.mobile.thermal.officialdex.radiometric.OfficialF2PaletteSnapshot;

/** App-side binding for observing official PreviewManagerII after G(byte[]) has completed. */
public final class PreviewManagerIIAppBinding {
    private static final int MAX_SCOPED_OFFLINE_CALLBACKS = 8;
    private static final Object lifecycleOperationLock = new Object();

    private static PreviewManagerII manager;
    private static PreviewManagerII terminalCloseRetryManager;
    private static Lifecycle installedLifecycle;
    private static long nextLifecycleGeneration;
    private static final WeakHashMap<PreviewManagerII, F2StreamCallback> callbacks = new WeakHashMap<>();
    private static final WeakHashMap<PreviewManagerII, Long> managerGenerations = new WeakHashMap<>();
    private static final WeakHashMap<PreviewManagerII, OfficialProcessedF2Frame> latestFrames = new WeakHashMap<>();
    private static final WeakHashMap<PreviewManagerII, LinkedHashMap<Integer, OfflineCallbackSnapshot>>
            offlineCallbacksByManager = new WeakHashMap<>();
    private static OsdBgCallbackBean latestOsd;

    private PreviewManagerIIAppBinding() {}

    public static PreviewManagerII installLifecycle(ComponentActivity activity) {
        if (activity == null) {
            throw new IllegalArgumentException("PreviewManagerII requires a non-null ComponentActivity lifecycle");
        }
        return installLifecycle(activity.getLifecycle());
    }

    static PreviewManagerII installLifecycle(Lifecycle lifecycle) {
        if (lifecycle == null) {
            throw new IllegalArgumentException("PreviewManagerII requires a non-null lifecycle");
        }
        synchronized (lifecycleOperationLock) {
            PreviewManagerII previous;
            Long previousGeneration;
            boolean retainedForTerminalRetry;
            boolean hasCurrentCallback;
            synchronized (PreviewManagerIIAppBinding.class) {
                if (manager != null && installedLifecycle == lifecycle) {
                    return manager;
                }
                previous = manager;
                previousGeneration = previous == null ? null : managerGenerations.get(previous);
                retainedForTerminalRetry =
                        previous != null && previous == terminalCloseRetryManager;
                hasCurrentCallback =
                        previous != null && callbacks.get(previous) != null;
            }

            boolean ownsActiveNativeStream = false;
            if (previous != null && hasCurrentCallback && previous.R() != null) {
                F2UsbModuleHelper helper = F2UsbModuleHelper.INSTANCE;
                ownsActiveNativeStream =
                        helper.activeUserId() >= 0 && helper.activeChannel() >= 0;
            }
            if (retainedForTerminalRetry || ownsActiveNativeStream) {
                previous.adoptHostLifecycle(lifecycle);
                synchronized (PreviewManagerIIAppBinding.class) {
                    Long currentGeneration = managerGenerations.get(previous);
                    boolean generationCurrent =
                            previous == manager
                                    && previousGeneration != null
                                    && previousGeneration.equals(currentGeneration);
                    boolean ownershipCurrent =
                            retainedForTerminalRetry
                                    ? previous == terminalCloseRetryManager
                                    : callbacks.get(previous) != null;
                    if (generationCurrent && ownershipCurrent) {
                        // Publish only after lifecycle adoption succeeds and the exact owner
                        // generation remains current.
                        if (terminalCloseRetryManager == previous) {
                            terminalCloseRetryManager = null;
                        }
                        installedLifecycle = lifecycle;
                        return previous;
                    }
                }
            }

            PreviewManagerII installed = new PreviewManagerII(lifecycle, false, false);
            synchronized (PreviewManagerIIAppBinding.class) {
                if (manager != previous
                        || (previous != null
                            && !java.util.Objects.equals(
                                    previousGeneration,
                                    managerGenerations.get(previous)))) {
                    throw new IllegalStateException(
                            "PreviewManagerII lifecycle owner changed during installation");
                }
                if (previous != null) clearManagerState(previous);
                manager = installed;
                activateManagerGeneration(installed);
                installedLifecycle = lifecycle;
            }
            if (previous != null) {
                previous.closePreviewCallback();
            }
            return installed;
        }
    }

    public static synchronized PreviewManagerII manager() {
        if (manager == null) {
            throw new IllegalStateException(
                    "PreviewManagerII lifecycle is not installed; construct OfficialPreviewHost with a ComponentActivity before using the official preview manager");
        }
        return manager;
    }

    public static void bind(PreviewManagerII manager, F2StreamCallback callback) {
        synchronized (lifecycleOperationLock) {
            PreviewManagerII current;
            synchronized (PreviewManagerIIAppBinding.class) {
                current = manager();
                if (manager != current) {
                    throw new IllegalStateException("stale PreviewManagerII cannot be bound after lifecycle replacement");
                }
                clearManagerState(current);
            }
            current.openPreviewCallback();
            synchronized (PreviewManagerIIAppBinding.class) {
                activateManagerGeneration(current);
                callbacks.put(current, callback);
            }
        }
    }

    /**
     * Invalidates the active callback generation before a USB reopen can fail.
     *
     * <p>The binding monitor is released before manager cleanup so a late frame handoff can only
     * observe the already-invalidated generation and cannot be published as part of the next USB
     * session.
     */
    public static void prepareForUsbReopen() {
        suspendForUsbTransition(manager());
    }

    /**
     * Invalidates app/processor work for a reversible native stop without
     * releasing the renderer or forgetting the currently attached surface.
     */
    public static void suspendForUsbTransition(PreviewManagerII requestedManager) {
        synchronized (lifecycleOperationLock) {
            PreviewManagerII current;
            synchronized (PreviewManagerIIAppBinding.class) {
                current = manager();
                if (requestedManager != current) {
                    throw new IllegalStateException(
                            "stale PreviewManagerII cannot be suspended after lifecycle replacement");
                }
                clearManagerState(current);
            }
            current.suspendF2PublicationForUsbTransition();
        }
    }

    public static synchronized void retainManagerForTerminalCloseRetry(PreviewManagerII requestedManager) {
        if (requestedManager == null || requestedManager != manager) {
            throw new IllegalStateException(
                    "only the current PreviewManagerII can own a terminal close retry");
        }
        terminalCloseRetryManager = requestedManager;
    }

    public static synchronized void releaseManagerFromTerminalCloseRetry(PreviewManagerII requestedManager) {
        if (terminalCloseRetryManager == requestedManager) {
            terminalCloseRetryManager = null;
        }
    }

    public static synchronized boolean isManagerRetainedForTerminalCloseRetry(
            PreviewManagerII requestedManager) {
        return requestedManager != null && requestedManager == terminalCloseRetryManager;
    }

    public static void transferTerminalCloseRetryManagerToExternalOwner() {
        synchronized (lifecycleOperationLock) {
            PreviewManagerII retained;
            synchronized (PreviewManagerIIAppBinding.class) {
                retained = terminalCloseRetryManager;
                if (retained == null || retained != manager) return;
                installedLifecycle = null;
            }
            retained.detachHostLifecycleForTerminalCloseRetry();
        }
    }

    public static void unbind(PreviewManagerII manager) {
        if (manager == null) return;
        synchronized (lifecycleOperationLock) {
            synchronized (PreviewManagerIIAppBinding.class) {
                clearManagerState(manager);
            }
            manager.closePreviewCallback();
        }
    }

    public static synchronized OfficialProcessedF2Frame latestOfficialProcessedFrame(
            PreviewManagerII manager, long frameCounter) {
        OfficialProcessedF2Frame frame = latestFrames.get(manager);
        Long generation = managerGenerations.get(manager);
        return manager == PreviewManagerIIAppBinding.manager
                && generation != null
                && frame != null
                && frame.frameCounter == frameCounter
                && frame.lifecycleGeneration == generation
                ? frame
                : null;
    }

    public static OfficialProcessedF2Frame latestOfficialProcessedFrameWithOfflineCapture(
            PreviewManagerII manager, long frameCounter, int displayWidth, int displayHeight) {
        return latestOfficialProcessedFrameWithOfflineCapture(
                manager,
                frameCounter,
                displayWidth,
                displayHeight,
                manager == null ? -1L : manager.currentRendererEpoch());
    }

    public static OfficialProcessedF2Frame latestOfficialProcessedFrameWithOfflineCapture(
            PreviewManagerII manager,
            long frameCounter,
            int displayWidth,
            int displayHeight,
            long expectedRendererEpoch) {
        Size captureSize = OfficialF2MeasurementCoordinator.INSTANCE.officialCaptureSize(
                OfficialF2MeasurementCoordinator.INSTANCE.officialModuleSubtype(Z2.g.a.U().getModuleID()),
                displayWidth,
                displayHeight);
        int captureWidth = captureSize.getWidth();
        int captureHeight = captureSize.getHeight();
        return latestOfficialProcessedFrameWithOfflineCapture(
                manager,
                frameCounter,
                captureSize,
                captureWidth,
                captureHeight,
                retryIndex -> manager.W(captureSize),
                expectedRendererEpoch,
                () -> manager.isOfficialRendererEpochCurrentSnapshot(expectedRendererEpoch));
    }

    public static OfficialProcessedF2Frame latestOfficialProcessedFrameWithOfflineCaptureForTests(
            PreviewManagerII manager,
            long frameCounter,
            int captureWidth,
            int captureHeight,
            IntFunction<d> supplier) {
        return latestOfficialProcessedFrameWithOfflineCapture(
                manager,
                frameCounter,
                new Size(captureWidth, captureHeight),
                captureWidth,
                captureHeight,
                supplier,
                -1L,
                () -> true);
    }

    private static OfficialProcessedF2Frame latestOfficialProcessedFrameWithOfflineCapture(
            PreviewManagerII requestedManager,
            long frameCounter,
            Size captureSize,
            int captureWidth,
            int captureHeight,
            IntFunction<d> supplier,
            long expectedRendererEpoch,
            BooleanSupplier rendererEpochCurrent) {
        CaptureInputs inputs;
        synchronized (PreviewManagerIIAppBinding.class) {
            inputs = captureInputs(requestedManager, frameCounter);
        }
        if (inputs == null) return null;
        if (!rendererEpochCurrent.getAsBoolean()) {
            return captureFailure(
                    inputs.frame,
                    "renderer_lifecycle_changed_before_capture expectedRendererEpoch="
                            + expectedRendererEpoch);
        }
        if (inputs.offline == null) {
            return captureFailure(inputs.frame, inputs.failureReason);
        }

        OfficialRendererJpegSelection jpeg = selectOfficialRendererJpeg(
                inputs.offline.frameNumStamp,
                captureSize,
                captureWidth,
                captureHeight,
                captureWidth + "x" + captureHeight,
                supplier,
                rendererEpochCurrent);
        if (!rendererEpochCurrent.getAsBoolean()) {
            return captureFailure(
                    inputs.frame,
                    "renderer_lifecycle_changed_after_capture expectedRendererEpoch="
                            + expectedRendererEpoch);
        }
        synchronized (PreviewManagerIIAppBinding.class) {
            Long currentGeneration = managerGenerations.get(requestedManager);
            if (requestedManager != manager
                    || currentGeneration == null
                    || currentGeneration.longValue() != inputs.generation) {
                return captureFailure(inputs.frame, "offline_capture_lifecycle_changed_fail_closed");
            }
        }
        return inputs.frame.withOfflineCapture(
                copyPreviewInfo(inputs.offline.previewInfo),
                inputs.offline.frameNumStamp,
                jpeg.jpegBytes,
                jpeg.source,
                jpeg.captureWidth,
                jpeg.captureHeight,
                jpeg.selectedFrameNumStamp,
                jpeg.timestampProvenance);
    }

    private static CaptureInputs captureInputs(PreviewManagerII requestedManager, long frameCounter) {
        if (requestedManager == null || requestedManager != manager) return null;
        Long generation = managerGenerations.get(requestedManager);
        OfficialProcessedF2Frame frame = latestFrames.get(requestedManager);
        if (generation == null
                || frame == null
                || frame.frameCounter != frameCounter
                || frame.lifecycleGeneration != generation.longValue()) {
            return null;
        }
        if (frame.processedFrameNumStamp < 0) {
            return new CaptureInputs(
                    frame,
                    generation,
                    null,
                    "offline_callback_frame_stamp_unavailable_fail_closed");
        }
        Map<Integer, OfflineCallbackSnapshot> scopedCallbacks = offlineCallbacksByManager.get(requestedManager);
        OfflineCallbackSnapshot offline = scopedCallbacks == null
                ? null
                : scopedCallbacks.get(frame.processedFrameNumStamp);
        if (offline == null) {
            return new CaptureInputs(
                    frame,
                    generation,
                    null,
                    "offline_callback_missing_for_requested_frame_fail_closed stamp="
                            + frame.processedFrameNumStamp);
        }
        if (offline.lifecycleGeneration != generation.longValue()
                || offline.associatedFrameCounter != frame.frameCounter
                || offline.frameNumStamp != frame.processedFrameNumStamp) {
            return new CaptureInputs(
                    frame,
                    generation,
                    null,
                    "offline_callback_not_associated_with_requested_frame_fail_closed");
        }
        return new CaptureInputs(frame, generation, offline.copy(), null);
    }

    private static OfficialProcessedF2Frame captureFailure(
            OfficialProcessedF2Frame frame, String reason) {
        return frame.withOfflineCapture(
                null,
                -1,
                null,
                reason,
                0,
                0,
                -1,
                OfficialProcessedF2Frame.RendererTimestampProvenance.NONE);
    }

    public static synchronized void onOsd(OsdBgCallbackBean bean) { latestOsd = bean; }

    /** Called only by PreviewManagerII.e with the manager that produced this callback. */
    public static boolean onOfflineCallback(
            PreviewManagerII callbackManager,
            PreviewInfoDataBean info,
            int stamp,
            long processingEpoch,
            long lifecycleGeneration) {
        if (callbackManager == null
                || !callbackManager.isProcessingEpochCurrentSnapshot(processingEpoch)) {
            return false;
        }
        synchronized (PreviewManagerIIAppBinding.class) {
            Long generation = managerGenerations.get(callbackManager);
            if (callbackManager != manager
                    || generation == null
                    || generation.longValue() != lifecycleGeneration
                    || !callbacks.containsKey(callbackManager)
                    || !callbackManager.isProcessingEpochCurrentSnapshot(processingEpoch)) {
                return false;
            }
            int payloadStamp = frameNumStamp(info);
            if (payloadStamp >= 0 && payloadStamp != stamp) return false;

            OfficialProcessedF2Frame currentFrame = latestFrames.get(callbackManager);
            long associatedFrameCounter = currentFrame != null
                    && currentFrame.lifecycleGeneration == generation.longValue()
                    && currentFrame.processedFrameNumStamp == stamp
                    ? currentFrame.frameCounter
                    : -1L;
            LinkedHashMap<Integer, OfflineCallbackSnapshot> scopedCallbacks =
                    offlineCallbacksByManager.computeIfAbsent(
                            callbackManager,
                            ignored -> new LinkedHashMap<>());
            if (!scopedCallbacks.containsKey(stamp)
                    && scopedCallbacks.size() >= MAX_SCOPED_OFFLINE_CALLBACKS) {
                Integer oldest = scopedCallbacks.keySet().iterator().next();
                scopedCallbacks.remove(oldest);
            }
            scopedCallbacks.put(
                    stamp,
                    new OfflineCallbackSnapshot(
                            generation,
                            associatedFrameCounter,
                            stamp,
                            copyPreviewInfo(info)));
            return true;
        }
    }

    public static synchronized long currentLifecycleGeneration(PreviewManagerII requestedManager) {
        if (requestedManager == null
                || requestedManager != manager
                || !callbacks.containsKey(requestedManager)) {
            return -1L;
        }
        Long generation = managerGenerations.get(requestedManager);
        return generation == null ? -1L : generation.longValue();
    }

    public static void afterOfficialG(
            PreviewManagerII manager,
            int userId,
            long frameCounter,
            int width,
            int height,
            int frameType,
            int dataType,
            int streamType,
            byte[] packet,
            int officialWidth,
            int officialHeight,
            PreviewStreamInfo streamInfo,
            boolean offline,
            String processorBucket) {
        afterOfficialG(
                manager,
                manager == null ? -1L : manager.currentProcessingEpoch(),
                userId,
                frameCounter,
                width,
                height,
                frameType,
                dataType,
                streamType,
                packet,
                officialWidth,
                officialHeight,
                streamInfo,
                offline,
                processorBucket);
    }

    public static void afterOfficialG(
            PreviewManagerII manager,
            long processingEpoch,
            int userId,
            long frameCounter,
            int width,
            int height,
            int frameType,
            int dataType,
            int streamType,
            byte[] packet,
            int officialWidth,
            int officialHeight,
            PreviewStreamInfo streamInfo,
            boolean offline,
            String processorBucket) {
        F2StreamCallback callback;
        F2StreamFrame callbackFrame;
        Long generation;
        if (manager == null || !manager.isProcessingEpochCurrentSnapshot(processingEpoch)) return;
        PreviewStreamInfo streamSnapshot = snapshot(streamInfo);
        int processedFrameNumStamp = frameNumStamp(streamSnapshot.getPreviewInfoData());
        PaletteCapture palette = capturePalette(manager);
        synchronized (PreviewManagerIIAppBinding.class) {
            if (manager != PreviewManagerIIAppBinding.manager) return;
            if (!manager.isProcessingEpochCurrentSnapshot(processingEpoch)) return;
            callback = callbacks.get(manager);
            generation = managerGenerations.get(manager);
            if (callback == null || generation == null) return;
        }

        OfficialProcessedF2Frame frame = new OfficialProcessedF2Frame(
                frameCounter,
                packet.length,
                officialWidth,
                officialHeight,
                streamSnapshot,
                offline,
                processorBucket,
                generation,
                processedFrameNumStamp,
                palette.snapshot,
                palette.source,
                null,
                -1,
                null,
                null,
                0,
                0,
                -1,
                OfficialProcessedF2Frame.RendererTimestampProvenance.NONE);
        if (!manager.recordAppHandoff(
                processingEpoch, userId, packet.length, streamType, frameCounter)) return;

        synchronized (PreviewManagerIIAppBinding.class) {
            if (!manager.isProcessingEpochCurrentSnapshot(processingEpoch)
                    || !isCurrentCallbackLocked(manager, generation.longValue(), callback)) return;
            latestFrames.put(manager, frame);

            LinkedHashMap<Integer, OfflineCallbackSnapshot> scopedCallbacks =
                    offlineCallbacksByManager.get(manager);
            if (scopedCallbacks != null) {
                OfflineCallbackSnapshot pending = scopedCallbacks.get(processedFrameNumStamp);
                if (pending != null && pending.lifecycleGeneration == generation.longValue()) {
                    scopedCallbacks.put(processedFrameNumStamp, pending.associate(frameCounter));
                }
            }
            callbackFrame = new F2StreamFrame(
                    userId,
                    frameCounter,
                    width,
                    height,
                    frameType,
                    dataType,
                    streamType,
                    packet,
                    generation);
        }
        if (!manager.isProcessingEpochCurrentSnapshot(processingEpoch)) return;
        try {
            callback.onFrame(callbackFrame);
        } catch (RuntimeException | LinkageError error) {
            System.err.println(
                    "PreviewManagerIIAppBinding callback failure "
                            + error.getClass().getSimpleName() + ": " + error.getMessage());
        }
    }

    private static boolean isCurrentCallbackLocked(
            PreviewManagerII requestedManager,
            long generation,
            F2StreamCallback callback) {
        Long currentGeneration = managerGenerations.get(requestedManager);
        return requestedManager == manager
                && currentGeneration != null
                && currentGeneration.longValue() == generation
                && callbacks.get(requestedManager) == callback;
    }

    public static synchronized boolean isCurrentLifecycleGeneration(long generation) {
        if (manager == null || generation < 0L) return false;
        Long currentGeneration = managerGenerations.get(manager);
        return currentGeneration != null
                && currentGeneration.longValue() == generation
                && callbacks.containsKey(manager);
    }

    private static PaletteCapture capturePalette(PreviewManagerII manager) {
        try {
            OfficialF2PaletteSnapshot current = manager.Q();
            if (current == null) {
                return new PaletteCapture(
                        OfficialF2PaletteSnapshot.absent(
                                OfficialF2PaletteSnapshot.AbsenceProof.PREVIEW_MANAGER_Q_RETURNED_NULL),
                        "preview_manager_Q_returned_actual_null");
            }
            return new PaletteCapture(current, "preview_manager_Q_present_snapshot");
        } catch (RuntimeException error) {
            return new PaletteCapture(
                    null,
                    "preview_manager_Q_unavailable_fail_closed: "
                            + error.getClass().getSimpleName() + ": " + error.getMessage());
        }
    }

    static OfficialRendererJpegSelection captureOfficialRendererJpeg(
            PreviewManagerII manager,
            int targetStamp,
            int displayWidth,
            int displayHeight,
            int officialWidth,
            int officialHeight) {
        Size captureSize = OfficialF2MeasurementCoordinator.INSTANCE.officialCaptureSize(
                OfficialF2MeasurementCoordinator.INSTANCE.officialModuleSubtype(Z2.g.a.U().getModuleID()),
                displayWidth,
                displayHeight);
        return selectOfficialRendererJpeg(targetStamp, captureSize, frame -> manager.W(captureSize));
    }

    static OfficialRendererJpegSelection selectOfficialRendererJpeg(
            int targetStamp, Size captureSize, IntFunction<d> supplier) {
        int captureWidth = captureSize.getWidth();
        int captureHeight = captureSize.getHeight();
        return selectOfficialRendererJpeg(
                targetStamp,
                captureSize,
                captureWidth,
                captureHeight,
                captureWidth + "x" + captureHeight,
                supplier,
                () -> true);
    }

    private static OfficialRendererJpegSelection selectOfficialRendererJpeg(
            int targetStamp,
            Size captureSize,
            int captureWidth,
            int captureHeight,
            String captureSizeText,
            IntFunction<d> supplier,
            BooleanSupplier rendererEpochCurrent) {
        byte[] nearestJpeg = null;
        int nearestStamp = -1;
        long nearestDistance = Long.MAX_VALUE;
        for (int retryIndex = 0; retryIndex < 50; retryIndex++) {
            if (!rendererEpochCurrent.getAsBoolean()) {
                return rendererLifecycleChangedSelection(
                        targetStamp,
                        captureSize,
                        captureWidth,
                        captureHeight);
            }
            d candidate = supplier.apply(retryIndex);
            if (hasJpeg(candidate)) {
                int candidateStamp = candidate.a();
                long distance = Math.abs((long) candidateStamp - targetStamp);
                if (candidateStamp == targetStamp) {
                    if (!rendererEpochCurrent.getAsBoolean()) {
                        return rendererLifecycleChangedSelection(
                                targetStamp,
                                captureSize,
                                captureWidth,
                                captureHeight);
                    }
                    return new OfficialRendererJpegSelection(
                            candidate.b(),
                            "renderer_jpeg_exact_timestamp retryIndex=" + retryIndex
                                    + " frameNumStamp=" + candidateStamp,
                            captureSize,
                            captureWidth,
                            captureHeight,
                            candidateStamp,
                            OfficialProcessedF2Frame.RendererTimestampProvenance.EXACT);
                }
                if (nearestJpeg == null || distance < nearestDistance) {
                    nearestJpeg = copy(candidate.b());
                    nearestStamp = candidateStamp;
                    nearestDistance = distance;
                }
            }
            try {
                Thread.sleep(10L);
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
                break;
            }
        }
        if (!rendererEpochCurrent.getAsBoolean()) {
            return rendererLifecycleChangedSelection(
                    targetStamp,
                    captureSize,
                    captureWidth,
                    captureHeight);
        }
        if (nearestJpeg != null) {
            return new OfficialRendererJpegSelection(
                    nearestJpeg,
                            "renderer_jpeg_nearest_timestamp target=" + targetStamp
                            + " selected=" + nearestStamp,
                    captureSize,
                    captureWidth,
                    captureHeight,
                    nearestStamp,
                    OfficialProcessedF2Frame.RendererTimestampProvenance.NEAREST);
        }
        return new OfficialRendererJpegSelection(
                null,
                "renderer_jpeg_missing_fail_closed target=" + targetStamp
                        + " size=" + captureSizeText,
                captureSize,
                captureWidth,
                captureHeight,
                -1,
                OfficialProcessedF2Frame.RendererTimestampProvenance.NONE);
    }

    private static OfficialRendererJpegSelection rendererLifecycleChangedSelection(
            int targetStamp,
            Size captureSize,
            int captureWidth,
            int captureHeight) {
        return new OfficialRendererJpegSelection(
                null,
                "renderer_lifecycle_changed_fail_closed target=" + targetStamp,
                captureSize,
                captureWidth,
                captureHeight,
                -1,
                OfficialProcessedF2Frame.RendererTimestampProvenance.NONE);
    }

    private static boolean hasJpeg(d candidate) {
        byte[] bytes = candidate == null ? null : candidate.b();
        return bytes != null
                && bytes.length >= 2
                && (bytes[0] & 0xff) == 0xff
                && (bytes[1] & 0xff) == 0xd8;
    }

    public static OfficialRendererJpegSelection selectOfficialRendererJpegForTests(
            int targetStamp,
            int captureWidth,
            int captureHeight,
            IntFunction<d> supplier) {
        return selectOfficialRendererJpeg(
                targetStamp,
                new Size(captureWidth, captureHeight),
                captureWidth,
                captureHeight,
                captureWidth + "x" + captureHeight,
                supplier,
                () -> true);
    }

    private static PreviewStreamInfo snapshot(PreviewStreamInfo streamInfo) {
        if (streamInfo == null) return new PreviewStreamInfo(new PreviewInfoDataBean(), null);
        return new PreviewStreamInfo(
                copyPreviewInfo(streamInfo.getPreviewInfoData()),
                streamInfo.getIStreamInfo());
    }

    private static PreviewInfoDataBean copyPreviewInfo(PreviewInfoDataBean source) {
        return source == null ? new PreviewInfoDataBean() : new PreviewInfoDataBean(
                copy(source.getByteArrSrc()),
                copy(source.getByteArrDst()),
                copy(source.getByteArrHead()),
                copy(source.getByteArrRawData()),
                copy(source.getByteArrRawAppendData()),
                copy(source.getByteArrYuvAppendData()),
                copy(source.getByteArrRawAppendLine2()),
                copy(source.getOffByteArrRawData()),
                copy(source.getOffByteArrRawAppendData()));
    }

    private static int frameNumStamp(PreviewInfoDataBean info) {
        if (info == null) return -1;
        byte[] append = info.getByteArrYuvAppendData();
        if (append == null || append.length == 0) return 0;
        if (append.length < 22) return -1;
        return (short) ((append[20] & 0xff) | ((append[21] & 0xff) << 8));
    }

    private static long activateManagerGeneration(PreviewManagerII manager) {
        long generation = ++nextLifecycleGeneration;
        managerGenerations.put(manager, generation);
        offlineCallbacksByManager.put(manager, new LinkedHashMap<>());
        return generation;
    }

    private static void clearManagerState(PreviewManagerII manager) {
        callbacks.remove(manager);
        latestFrames.remove(manager);
        managerGenerations.remove(manager);
        offlineCallbacksByManager.remove(manager);
        latestOsd = null;
    }

    public static final class OfficialRendererJpegSelection {
        public final byte[] jpegBytes;
        public final String source;
        public final Size captureSize;
        public final int captureWidth;
        public final int captureHeight;
        public final int selectedFrameNumStamp;
        public final OfficialProcessedF2Frame.RendererTimestampProvenance timestampProvenance;

        OfficialRendererJpegSelection(
                byte[] jpegBytes,
                String source,
                Size captureSize,
                int captureWidth,
                int captureHeight,
                int selectedFrameNumStamp,
                OfficialProcessedF2Frame.RendererTimestampProvenance timestampProvenance) {
            this.jpegBytes = copy(jpegBytes);
            this.source = source;
            this.captureSize = captureSize;
            this.captureWidth = captureWidth;
            this.captureHeight = captureHeight;
            this.selectedFrameNumStamp = selectedFrameNumStamp;
            this.timestampProvenance = timestampProvenance;
        }
    }

    private static final class PaletteCapture {
        final OfficialF2PaletteSnapshot snapshot;
        final String source;

        PaletteCapture(OfficialF2PaletteSnapshot snapshot, String source) {
            this.snapshot = snapshot;
            this.source = source;
        }
    }

    private static final class CaptureInputs {
        final OfficialProcessedF2Frame frame;
        final long generation;
        final OfflineCallbackSnapshot offline;
        final String failureReason;

        CaptureInputs(
                OfficialProcessedF2Frame frame,
                long generation,
                OfflineCallbackSnapshot offline,
                String failureReason) {
            this.frame = frame;
            this.generation = generation;
            this.offline = offline;
            this.failureReason = failureReason;
        }
    }

    private static final class OfflineCallbackSnapshot {
        final long lifecycleGeneration;
        final long associatedFrameCounter;
        final int frameNumStamp;
        final PreviewInfoDataBean previewInfo;

        OfflineCallbackSnapshot(
                long lifecycleGeneration,
                long associatedFrameCounter,
                int frameNumStamp,
                PreviewInfoDataBean previewInfo) {
            this.lifecycleGeneration = lifecycleGeneration;
            this.associatedFrameCounter = associatedFrameCounter;
            this.frameNumStamp = frameNumStamp;
            this.previewInfo = previewInfo;
        }

        OfflineCallbackSnapshot associate(long frameCounter) {
            return new OfflineCallbackSnapshot(
                    lifecycleGeneration,
                    frameCounter,
                    frameNumStamp,
                    previewInfo);
        }

        OfflineCallbackSnapshot copy() {
            return new OfflineCallbackSnapshot(
                    lifecycleGeneration,
                    associatedFrameCounter,
                    frameNumStamp,
                    copyPreviewInfo(previewInfo));
        }
    }

    private static byte[] copy(byte[] value) {
        if (value == null || value.length == 0) return new byte[0];
        byte[] copy = new byte[value.length];
        System.arraycopy(value, 0, copy, 0, value.length);
        return copy;
    }
}
