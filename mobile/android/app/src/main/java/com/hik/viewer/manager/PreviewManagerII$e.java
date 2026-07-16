package com.hik.viewer.manager;
import com.hik.f1module.hcusbcamerasdk.callback.IStreamCallback;
import com.sun.jna.Pointer;
final class PreviewManagerII$e implements IStreamCallback { final PreviewManagerII a; PreviewManagerII$e(PreviewManagerII manager){this.a=manager;} @Override public int invoke(Pointer data,int length){return 0;} }
