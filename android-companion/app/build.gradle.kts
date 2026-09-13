plugins { id("com.android.application") }

android {
    namespace = "buzz.walnutnest.bridge"
    compileSdk = 36

    defaultConfig {
        applicationId = "buzz.walnutnest.bridge"
        minSdk = 30
        targetSdk = 36
        versionCode = 7
        versionName = "0.2.5"
    }

    val signingStore = System.getenv("ANDROID_SIGNING_STORE_FILE")
    if (!signingStore.isNullOrBlank()) {
        signingConfigs {
            create("ci") {
                storeFile = file(signingStore)
                storePassword = System.getenv("ANDROID_SIGNING_STORE_PASSWORD")
                keyAlias = System.getenv("ANDROID_SIGNING_KEY_ALIAS")
                keyPassword = System.getenv("ANDROID_SIGNING_KEY_PASSWORD")
            }
        }
        buildTypes {
            getByName("debug") {
                signingConfig = signingConfigs.getByName("ci")
            }
        }
    }
}
