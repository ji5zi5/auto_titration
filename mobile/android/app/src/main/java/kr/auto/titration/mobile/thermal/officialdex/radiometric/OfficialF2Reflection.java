package kr.auto.titration.mobile.thermal.officialdex.radiometric;

import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;

/** Small reflection helper that always resolves official classes from the child loader. */
final class OfficialF2Reflection {
    private final ClassLoader childLoader;

    OfficialF2Reflection(ClassLoader childLoader) {
        this.childLoader = childLoader;
    }

    Class<?> type(String className) throws ClassNotFoundException {
        return Class.forName(className, false, childLoader);
    }

    Class<?> initializedType(String className) throws ClassNotFoundException {
        return Class.forName(className, true, childLoader);
    }

    Object singleton(String className, String fieldName) throws ReflectiveOperationException {
        return staticField(initializedType(className), fieldName);
    }

    Object staticField(Class<?> owner, String fieldName) throws ReflectiveOperationException {
        Field field = owner.getDeclaredField(fieldName);
        field.setAccessible(true);
        return field.get(null);
    }

    Object newInstance(String className) throws ReflectiveOperationException {
        Constructor<?> constructor = initializedType(className).getDeclaredConstructor();
        constructor.setAccessible(true);
        return constructor.newInstance();
    }

    Method method(Class<?> owner, String name, Class<?>... parameterTypes) throws NoSuchMethodException {
        Method method = owner.getDeclaredMethod(name, parameterTypes);
        method.setAccessible(true);
        return method;
    }

    Object invoke(Method method, Object receiver, Object... args) throws ReflectiveOperationException {
        try {
            return method.invoke(receiver, args);
        } catch (InvocationTargetException e) {
            Throwable target = e.getTargetException();
            if (target instanceof ReflectiveOperationException) {
                throw (ReflectiveOperationException) target;
            }
            if (target instanceof RuntimeException) {
                throw (RuntimeException) target;
            }
            if (target instanceof Error) {
                throw (Error) target;
            }
            throw e;
        }
    }
}
