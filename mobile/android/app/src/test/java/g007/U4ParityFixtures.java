package g007;

import U4.a;
import U4.f;
import U4.i;

public final class U4ParityFixtures {
    private U4ParityFixtures() {}

    @f
    public static class Child {
        @i(order = 0) public short x;
        @i(order = 1) public int y;
    }

    @f
    public static class Header {
        @i(order = 0) public int magic;
        @i(order = 1) public short version;
        @i(order = 2) public byte flags;
        @i(order = 3) public float temp;
        @i(order = 4) public Child child = new Child();
        @i(order = 5) @a(fieldName = "values") public int count;
        @i(order = 6) public int[] values = new int[0];
        @i(order = 7) public byte[] tail = new byte[3];
    }

    @f
    public static class AccessorLength {
        @i(order = 0) @a(fieldName = "values") private int count;
        @i(order = 1) private int[] values = new int[0];
        @i(order = 2) private boolean active;

        public int getCount() { return count; }
        public void setCount(int count) { this.count = count; }
        public int[] getValues() { return values; }
        public void setValues(int[] values) { this.values = values; }
        public boolean isActive() { return active; }
        public void setActive(boolean active) { this.active = active; }
    }

    @f
    public static class ObjectArrayHolder {
        @i(order = 0) @a(fieldName = "children") public int count;
        @i(order = 1) public Child[] children = new Child[0];
    }

    @f
    public static class PrivatePrimitive {
        @i(order = 0) private int value;
        public int getValue() { return value; }
        public void setValue(int value) { this.value = value; }
    }

    @f
    public static class Parent {
        @i(order = 0) public int parentValue;
    }

    @f
    public static class ChildWithInheritedField extends Parent {
        @i(order = 0) public int childValue;
    }

    @f
    public static class NullArrayHolder {
        @i(order = 0) public byte[] bytes;
    }

    @f
    public static class NullObjectHolder {
        @i(order = 0) public Child child;
    }
}
