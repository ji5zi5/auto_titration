package com.hik.viewer.manager;
import androidx.lifecycle.DefaultLifecycleObserver;
import androidx.lifecycle.LifecycleOwner;
final class PreviewManagerII$defaultLifecycleObserver$1 implements DefaultLifecycleObserver { final PreviewManagerII a; PreviewManagerII$defaultLifecycleObserver$1(PreviewManagerII manager){this.a=manager;} @Override public void onCreate(LifecycleOwner owner){a.onOfficialLifecycleCreate();} @Override public void onDestroy(LifecycleOwner owner){a.onOfficialLifecycleDestroy(owner);} @Override public void onPause(LifecycleOwner owner){a.onOfficialLifecyclePause();} @Override public void onStart(LifecycleOwner owner){a.onOfficialLifecycleStart();} @Override public void onStop(LifecycleOwner owner){a.onOfficialLifecycleStop();} }
