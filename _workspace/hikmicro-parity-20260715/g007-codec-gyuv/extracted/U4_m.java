package U4;
public class m extends U4.l {
    private java.io.ByteArrayOutputStream a;
    protected java.io.DataOutput b;

    public m(java.io.OutputStream p1, java.nio.ByteOrder p2)
    {
        this.o0(p1, p2);
        this.a = ((java.io.ByteArrayOutputStream) p1);
        return;
    }

    public m(java.nio.ByteOrder p2)
    {
        this(new java.io.ByteArrayOutputStream(), p2);
        return;
    }

    public void I(byte p2)
    {
        this.b.writeByte(p2);
        return;
    }

    public void Q(byte[] p3, int p4)
    {
        if (p4 != 0) {
            if ((p4 == -1) || (p4 > p3.length)) {
                p4 = p3.length;
            }
            this.b.write(p3, 0, p4);
            return;
        } else {
            return;
        }
    }

    public void S(char p2)
    {
        this.b.writeChar(p2);
        return;
    }

    public void a0(char[] p4, int p5)
    {
        if ((p5 == -1) || (p5 > p4.length)) {
            p5 = p4.length;
        }
        int v0_1 = 0;
        while (v0_1 < p5) {
            this.b.writeChar(p4[v0_1]);
            v0_1++;
        }
        return;
    }

    public void b0(double p2)
    {
        this.b.writeDouble(p2);
        return;
    }

    public void c(boolean p2)
    {
        this.b.writeBoolean(p2);
        return;
    }

    public void c0(double[] p5, int p6)
    {
        if ((p6 == -1) || (p6 > p5.length)) {
            p6 = p5.length;
        }
        int v0_1 = 0;
        while (v0_1 < p6) {
            this.b.writeDouble(p5[v0_1]);
            v0_1++;
        }
        return;
    }

    public void e0(float p2)
    {
        this.b.writeFloat(p2);
        return;
    }

    public void f0(float[] p4, int p5)
    {
        if ((p5 == -1) || (p5 > p4.length)) {
            p5 = p4.length;
        }
        int v0_1 = 0;
        while (v0_1 < p5) {
            this.b.writeFloat(p4[v0_1]);
            v0_1++;
        }
        return;
    }

    public void g0(int p2)
    {
        this.b.writeInt(p2);
        return;
    }

    public void h0(int[] p4, int p5)
    {
        if ((p5 == -1) || (p5 > p4.length)) {
            p5 = p4.length;
        }
        int v0_1 = 0;
        while (v0_1 < p5) {
            this.b.writeInt(p4[v0_1]);
            v0_1++;
        }
        return;
    }

    public void i0(long p2)
    {
        this.b.writeLong(p2);
        return;
    }

    public void j0(long[] p5, int p6)
    {
        if ((p6 == -1) || (p6 > p5.length)) {
            p6 = p5.length;
        }
        int v0_1 = 0;
        while (v0_1 < p6) {
            this.b.writeLong(p5[v0_1]);
            v0_1++;
        }
        return;
    }

    public void l0(Object[] p3, int p4)
    {
        if ((p3 != null) && (p4 != 0)) {
            if ((p4 == -1) || (p4 > p3.length)) {
                p4 = p3.length;
            }
            int v0_0 = 0;
            while (v0_0 < p4) {
                this.k0(p3[v0_0]);
                v0_0++;
            }
        }
        return;
    }

    public void m0(short p2)
    {
        this.b.writeShort(p2);
        return;
    }

    public void n0(short[] p4, int p5)
    {
        if ((p5 == -1) || (p5 > p4.length)) {
            p5 = p4.length;
        }
        int v0_1 = 0;
        while (v0_1 < p5) {
            this.b.writeShort(p4[v0_1]);
            v0_1++;
        }
        return;
    }

    protected void o0(java.io.OutputStream p2, java.nio.ByteOrder p3)
    {
        if (p3 != java.nio.ByteOrder.LITTLE_ENDIAN) {
            this.b = new java.io.DataOutputStream(p2);
        } else {
            this.b = new U4.e(p2);
        }
        return;
    }

    public byte[] p0(Object p1)
    {
        this.k0(p1);
        return this.a.toByteArray();
    }

    public void q(boolean[] p4, int p5)
    {
        if ((p5 == -1) || (p5 > p4.length)) {
            p5 = p4.length;
        }
        int v0_1 = 0;
        while (v0_1 < p5) {
            this.b.writeBoolean(p4[v0_1]);
            v0_1++;
        }
        return;
    }
}
