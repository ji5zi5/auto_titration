package com.hik.viewer.manager;
import android.view.SurfaceHolder;
final class PreviewManagerII$g implements SurfaceHolder.Callback { final PreviewManagerII a; PreviewManagerII$g(PreviewManagerII manager){this.a=manager;} @Override public void surfaceCreated(SurfaceHolder holder){a.onOfficialSurfaceCreated();} @Override public void surfaceChanged(SurfaceHolder holder,int format,int width,int height){} @Override public void surfaceDestroyed(SurfaceHolder holder){a.onOfficialSurfaceDestroyed();} }
