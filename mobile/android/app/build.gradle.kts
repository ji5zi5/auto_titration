import org.gradle.api.GradleException
import org.jetbrains.kotlin.gradle.dsl.JvmTarget
import java.security.MessageDigest
import java.util.zip.ZipFile

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "kr.auto.titration.mobile"
    compileSdk = 35

    defaultConfig {
        applicationId = "kr.auto.titration.mobile"
        minSdk = 26
        targetSdk = 35
        versionCode = 6
        versionName = "0.1.5-mobile-prediction"

        ndk {
            abiFilters += "arm64-v8a"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    sourceSets {
        getByName("main") {
            assets.srcDirs("src/main/assets", rootProject.file("../../website"))
        }
    }

    androidResources {
        noCompress += "tflite"
    }

    packaging {
        jniLibs {
            useLegacyPackaging = true
        }
    }

    lint {
        // AndroidX Lifecycle lint currently crashes against Kotlin 2.3 analysis APIs
        // before reporting project issues; disable only that detector so lintDebug can run.
        disable += "NullSafeMutableLiveData"
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

dependencies {
    val cameraxVersion = "1.4.1"
    val liteRtVersion = "2.1.5"
    // Locked LiteRT coordinate: com.google.ai.edge.litert:litert:2.1.5

    implementation("androidx.activity:activity-ktx:1.10.1")
    implementation("androidx.fragment:fragment-ktx:1.8.6")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.camera:camera-core:$cameraxVersion")
    implementation("androidx.camera:camera-camera2:$cameraxVersion")
    implementation("androidx.camera:camera-lifecycle:$cameraxVersion")
    implementation("androidx.camera:camera-view:$cameraxVersion")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.1")
    implementation("net.java.dev.jna:jna:5.18.1@aar")
    implementation("com.google.ai.edge.litert:litert:$liteRtVersion")
    implementation("com.google.code.gson:gson:2.11.0")

    testImplementation("junit:junit:4.13.2")
}

data class OfficialArtifact(
    val sha256: String,
    val bundledPath: String,
)

val officialArtifactManifest =
    layout.projectDirectory.file("src/test/evidence/HIKMICRO_VIEWER_2_6_0_OFFICIAL_ARTIFACT_SHA256.tsv")

fun sha256(file: File): String {
    val digest = MessageDigest.getInstance("SHA-256")
    file.inputStream().buffered().use { input ->
        val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
        while (true) {
            val read = input.read(buffer)
            if (read < 0) break
            digest.update(buffer, 0, read)
        }
    }
    return digest.digest().joinToString("") { "%02x".format(it) }
}

fun officialArtifacts(): List<OfficialArtifact> =
    officialArtifactManifest.asFile.readLines()
        .filterNot { it.isBlank() || it.startsWith("#") }
        .map { line ->
            val columns = line.split('\t')
            require(columns.size >= 3) { "Malformed official-artifact manifest row: $line" }
            OfficialArtifact(columns[0], columns[2])
        }

fun publicDeliveryFindings(
    archive: File? = null,
    includeSourceTree: Boolean = true,
): List<String> {
    val findings = linkedSetOf<String>()
    val artifacts = officialArtifacts()
    val officialHashes = artifacts.mapTo(hashSetOf()) { it.sha256 }
    val repositoryRoot = rootProject.projectDir.parentFile.parentFile

    if (includeSourceTree) {
        layout.projectDirectory.dir("src/main").asFile.walkTopDown()
            .filter { it.isFile }
            .forEach { sourceFile ->
                if (sha256(sourceFile) in officialHashes) {
                    findings +=
                        "manifest-matching official bytes: ${sourceFile.relativeTo(repositoryRoot).invariantSeparatorsPath}"
                }
            }

        val guardedSourceRoots = listOf(
            "src/main/assets/hikmicro/official",
            "src/main/jniLibs",
            "src/main/java/com/hcusbsdk",
            "src/main/java/com/hik",
            "src/main/java/com/hikmicro",
            "src/main/java/hik/common",
        )
        guardedSourceRoots.forEach { relative ->
            val path = layout.projectDirectory.dir(relative).asFile
            if (path.exists()) findings += "official/vendor source path: mobile/android/app/$relative"
        }
    }

    if (archive != null) {
        require(archive.isFile) { "Public-deliverable archive does not exist: $archive" }
        ZipFile(archive).use { zip ->
            zip.entries().asSequence()
                .filterNot { it.isDirectory }
                .forEach { entry ->
                    val entryPath = entry.name
                    val pathIsGuarded =
                        entryPath.startsWith("assets/hikmicro/official/") ||
                            entryPath.startsWith("lib/") ||
                            entryPath.contains("/com/hcusbsdk/") ||
                            entryPath.contains("/com/hik/") ||
                            entryPath.contains("/com/hikmicro/") ||
                            entryPath.contains("/hik/common/")
                    val digest = MessageDigest.getInstance("SHA-256")
                    zip.getInputStream(entry).buffered().use { input ->
                        val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                        while (true) {
                            val read = input.read(buffer)
                            if (read < 0) break
                            digest.update(buffer, 0, read)
                        }
                    }
                    val entryHash = digest.digest().joinToString("") { "%02x".format(it) }
                    if (pathIsGuarded) findings += "official/vendor archive path: $entryPath"
                    if (entryHash in officialHashes) {
                        findings += "manifest-matching official archive bytes: $entryPath"
                    }
                }
        }
    }

    return findings.toList().sorted()
}

fun blockedPublicDeliveryMessage(findings: List<String>): String = buildString {
    appendLine("PUBLIC_DELIVERABLE_BLOCKED: this private lab source tree is non-redistributable.")
    appendLine(
        "No Gradle boolean, including -PhikmicroRedistributionApproved=true, grants " +
            "redistribution authority.",
    )
    appendLine(
        "Do not push/publish release APKs or this official-byte source tree. " +
            "Use debug/private lab sideload builds only.",
    )
    appendLine("A public deliverable requires a separately reviewed source tree with official bytes/vendor paths removed.")
    findings.take(30).forEach { appendLine(" - $it") }
    if (findings.size > 30) appendLine(" - ... and ${findings.size - 30} more finding(s)")
}

tasks.register("auditPublicDeliverable") {
    group = "verification"
    description = "Fails if the source tree or optional -PpublicDeliverablePath archive contains guarded official content."
    doLast {
        val archive = providers.gradleProperty("publicDeliverablePath").orNull?.let(::file)
        val findings = publicDeliveryFindings(archive)
        if (findings.isNotEmpty()) {
            throw GradleException(blockedPublicDeliveryMessage(findings))
        }
        logger.lifecycle("PUBLIC_DELIVERABLE_AUDIT_OK: no guarded official content found.")
    }
}

tasks.register("auditPublicDeliverableArchive") {
    group = "verification"
    description =
        "Audits only -PpublicDeliverablePath archive bytes/paths; it does not authorize this source tree or a release."
    doLast {
        val archive = providers.gradleProperty("publicDeliverablePath").orNull?.let(::file)
            ?: throw GradleException(
                "PUBLIC_DELIVERABLE_ARCHIVE_AUDIT_REQUIRES_PATH: pass -PpublicDeliverablePath=<zip-or-apk>.",
            )
        val findings = publicDeliveryFindings(archive, includeSourceTree = false)
        if (findings.isNotEmpty()) {
            throw GradleException(blockedPublicDeliveryMessage(findings))
        }
        logger.lifecycle(
            "PUBLIC_DELIVERABLE_ARCHIVE_AUDIT_OK: archive contains no manifest-matching official " +
                "bytes or guarded official/native/vendor paths. This does not authorize the current source tree.",
        )
    }
}

gradle.taskGraph.whenReady {
    val publicPackagingTaskNames = setOf(
        "assemblerelease",
        "bundlerelease",
        "packagerelease",
        "packagereleasebundle",
        "packagereleaseuniversalapk",
        "makeapkfrombundleforrelease",
        "extractapksforrelease",
        "extractapksfrombundleforrelease",
        "zipapksforrelease",
        "signreleasebundle",
        "asartocompatsplitsforrelease",
    )
    val requestsPublicPackage = allTasks.any { task ->
        val name = task.name.lowercase()
        task.project == project &&
            (name in publicPackagingTaskNames || name.startsWith("publish"))
    }
    if (requestsPublicPackage) {
        val findings = publicDeliveryFindings()
        if (findings.isNotEmpty()) {
            throw GradleException(blockedPublicDeliveryMessage(findings))
        }
    }
}
