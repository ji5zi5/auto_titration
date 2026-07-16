import org.gradle.api.GradleException
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

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
        versionCode = 4
        versionName = "0.1.3"

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

val hikmicroRedistributionApproved = providers.gradleProperty("hikmicroRedistributionApproved")
    .map { it.equals("true", ignoreCase = true) }
    .orElse(false)

tasks.configureEach {
    if (name.contains("Release", ignoreCase = true)) {
        doFirst {
            if (!hikmicroRedistributionApproved.get()) {
                throw GradleException(
                    "Release/deliverable APK blocked: HIKMICRO private native-library redistribution " +
                        "is not approved. Use debug/private lab sideload builds only, or pass " +
                        "-PhikmicroRedistributionApproved=true after attaching license evidence.",
                )
            }
        }
    }
}
