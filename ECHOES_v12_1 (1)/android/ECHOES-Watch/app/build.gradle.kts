plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "app.echoes.watch"
    compileSdk = 34

    defaultConfig {
        applicationId = "app.echoes.watch"
        minSdk = 30          // Wear OS 3+
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

// Only one small library: ZXing core, to draw the pairing QR on the watch.
// Everything else is the Android framework (LocationManager, HttpURLConnection, org.json).
dependencies {
    implementation("com.google.zxing:core:3.5.3")
}
