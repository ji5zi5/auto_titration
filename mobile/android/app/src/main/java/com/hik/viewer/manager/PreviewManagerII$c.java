package com.hik.viewer.manager;

import java.util.Comparator;
import kotlin.comparisons.ComparisonsKt;

public final class PreviewManagerII$c implements Comparator<Object> {
    public PreviewManagerII$c() { }
    @Override
    public final int compare(Object first, Object second) {
        return ComparisonsKt.compareValues(Float.valueOf(((Q2.k) first).c()), Float.valueOf(((Q2.k) second).c()));
    }
}
