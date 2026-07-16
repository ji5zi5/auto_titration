package com.hcusbsdk.Interface

class USB_USER_LOGIN_INFO {
    var dwSize: Int = 0
    @JvmField var dwTimeout: Int = 0
    @JvmField var dwDevIndex: Int = 0
    @JvmField var dwVID: Int = 0
    @JvmField var dwPID: Int = 0
    @JvmField var szUserName: String = ""
    @JvmField var szPassword: String = ""
    @JvmField var szSerialNumber: String = ""
    @JvmField var byLoginMode: Byte = 0
    var byRes2: ByteArray = ByteArray(3)
    @JvmField var dwFd: Int = 0
    var byRes: ByteArray = ByteArray(248)
}
