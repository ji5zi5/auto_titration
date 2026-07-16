package U4;
public class n extends U4.k {
    java.io.DataInput a;

    public n(java.io.InputStream p1, java.nio.ByteOrder p2)
    {
        this.l0(p1, p2);
        return;
    }

    public n(byte[] p2, java.nio.ByteOrder p3)
    {
        this(new java.io.ByteArrayInputStream(p2), p3);
        return;
    }

    protected void I(byte[] p2)
    {
        this.a.readFully(p2);
        return;
    }

    protected char Q()
    {
        return this.a.readChar();
    }

    protected void S(char[] p3)
    {
        int v0 = 0;
        while (v0 < p3.length) {
            p3[v0] = this.Q();
            v0++;
        }
        return;
    }

    protected double a0()
    {
        return this.a.readDouble();
    }

    protected void b0(double[] p4)
    {
        int v0 = 0;
        while (v0 < p4.length) {
            p4[v0] = this.a0();
            v0++;
        }
        return;
    }

    protected boolean c()
    {
        return this.a.readBoolean();
    }

    protected float d0()
    {
        return this.a.readFloat();
    }

    protected void e0(float[] p3)
    {
        int v0 = 0;
        while (v0 < p3.length) {
            p3[v0] = this.d0();
            v0++;
        }
        return;
    }

    protected void f0(int[] p3)
    {
        int v0 = 0;
        while (v0 < p3.length) {
            p3[v0] = this.readInt();
            v0++;
        }
        return;
    }

    protected long g0()
    {
        return this.a.readLong();
    }

    protected void h0(long[] p4)
    {
        int v0 = 0;
        while (v0 < p4.length) {
            p4[v0] = this.g0();
            v0++;
        }
        return;
    }

    public void i0(Object p18)
    {
        if (p18 == null) {
            throw new U4.h("Struct objects cannot be null.");
        } else {
            String v2_14 = U4.o.a(p18);
            String v3_0 = v2_14.b();
            int v4 = v3_0.length;
            int v6 = 0;
            while (v6 < v4) {
                reflect.Field v7 = v3_0[v6];
                U4.j v8_1 = v2_14.a(v7.getName());
                if (v8_1 == null) {
                    String v2_11 = new StringBuilder();
                    v2_11.append("Field Data not found for field: ");
                    v2_11.append(v7.getName());
                    throw new U4.h(v2_11.toString());
                } else {
                    int v12_0;
                    Object v9_4;
                    if (!v2_14.f(v7)) {
                        v9_4 = -1;
                        v12_0 = 0;
                    } else {
                        Object v9_8 = v2_14.a(v2_14.d(v7.getName()).getName());
                        if (!v9_8.f()) {
                            v9_4 = ((Number) v9_8.a().get(p18)).intValue();
                        } else {
                            v9_4 = ((Number) v9_8.b().invoke(p18, 0)).intValue();
                        }
                        v12_0 = 1;
                    }
                    if (!v8_1.f()) {
                        if ((v12_0 != 0) && (v9_4 >= null)) {
                            Object v13_4 = reflect.Array.newInstance(v7.getType().getComponentType(), v9_4);
                            v7.set(p18, v13_4);
                            if (!v7.getType().getComponentType().isPrimitive()) {
                                int v14_0 = 0;
                                while (v14_0 < v9_4) {
                                    ((Object[]) v13_4)[v14_0] = v7.getType().getComponentType().newInstance();
                                    v14_0++;
                                }
                            }
                        }
                        if ((v12_0 == 0) && (v7.getType().isArray())) {
                            if (v7.get(p18) == null) {
                                String v2_0 = new StringBuilder();
                                v2_0.append("Arrays can not be null. : ");
                                v2_0.append(v7.getName());
                                throw new U4.h(v2_0.toString());
                            } else {
                            }
                        }
                        if ((v12_0 == 0) || ((v12_0 == 1) && (v9_4 >= null))) {
                            this.c0(v8_1, 0, 0, p18);
                        }
                    } else {
                        reflect.Method v11_0 = v8_1.b();
                        Object v13_0 = v8_1.c();
                        if ((v11_0 == null) || (v13_0 == null)) {
                            String v2_3 = new StringBuilder();
                            v2_3.append(" getter/setter required for : ");
                            v2_3.append(v7.getName());
                            throw new U4.h(v2_3.toString());
                        } else {
                            if ((v12_0 != 0) && (v9_4 >= null)) {
                                int v14_3 = reflect.Array.newInstance(v7.getType().getComponentType(), v9_4);
                                v13_0.invoke(p18, new Object[] {v14_3}));
                                if (!v7.getType().getComponentType().isPrimitive()) {
                                    int v15_7 = 0;
                                    while (v15_7 < v9_4) {
                                        ((Object[]) v14_3)[v15_7] = v7.getType().getComponentType().newInstance();
                                        v15_7++;
                                    }
                                }
                            }
                            if ((v12_0 == 0) && (v7.getType().isArray())) {
                                if (v11_0.invoke(p18, 0) == null) {
                                    String v2_6 = new StringBuilder();
                                    v2_6.append("Arrays can not be null :");
                                    v2_6.append(v7.getName());
                                    throw new U4.h(v2_6.toString());
                                } else {
                                }
                            }
                            this.c0(v8_1, v11_0, v13_0, p18);
                        }
                    }
                    v6++;
                }
            }
            return;
        }
    }

    protected void j0(Object[] p3)
    {
        int v0 = 0;
        while (v0 < p3.length) {
            this.i0(p3[v0]);
            v0++;
        }
        return;
    }

    protected void k0(short[] p3)
    {
        int v0 = 0;
        while (v0 < p3.length) {
            p3[v0] = this.readShort();
            v0++;
        }
        return;
    }

    protected void l0(java.io.InputStream p2, java.nio.ByteOrder p3)
    {
        if (p3 != java.nio.ByteOrder.LITTLE_ENDIAN) {
            this.a = new java.io.DataInputStream(p2);
        } else {
            this.a = new U4.d(p2);
        }
        return;
    }

    public void m0(Object p1)
    {
        this.i0(p1);
        return;
    }

    protected void q(boolean[] p3)
    {
        int v0 = 0;
        while (v0 < p3.length) {
            p3[v0] = this.c();
            v0++;
        }
        return;
    }

    protected byte readByte()
    {
        return this.a.readByte();
    }

    protected int readInt()
    {
        return this.a.readInt();
    }

    protected short readShort()
    {
        return this.a.readShort();
    }
}
