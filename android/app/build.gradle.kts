import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// Версия Android-клиента идёт своей нумерацией: у десктопа 3.x, у телефона — 1.x.
val appVersionName = "1.0.0"
val appVersionCode = 1

// Ключ подписи хранится вне репозитория. Путь к файлу с его параметрами
// задаётся переменной SADNESS_SIGNING или лежит рядом: ../../signing.properties
// не коммитится (.gitignore). Без него собирается только отладочная версия.
val signingProps = Properties().apply {
    val path = System.getenv("SADNESS_SIGNING") ?: rootProject.file("signing.properties").path
    val file = File(path)
    if (file.isFile) file.inputStream().use { load(it) }
}

android {
    namespace = "com.sadness.vpn"
    compileSdk = 36
    ndkVersion = "28.2.13676358"

    defaultConfig {
        applicationId = "com.sadness.vpn"
        minSdk = 26
        targetSdk = 36
        versionCode = appVersionCode
        versionName = appVersionName
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        externalNativeBuild {
            cmake { cppFlags += "" }
        }
    }

    signingConfigs {
        if (signingProps.getProperty("storeFile") != null) {
            create("release") {
                storeFile = File(signingProps.getProperty("storeFile"))
                storePassword = signingProps.getProperty("storePassword")
                keyAlias = signingProps.getProperty("keyAlias")
                keyPassword = signingProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.findByName("release")
        }
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
    }

    // Ядро Mihomo — 50 МБ на архитектуру, поэтому отдельный APK под каждую.
    splits {
        abi {
            isEnable = true
            reset()
            include("arm64-v8a", "armeabi-v7a", "x86_64")
            isUniversalApk = false
        }
    }

    packaging {
        // libmihomo.so — программа, а не библиотека: она должна лежать распакованной
        // в nativeLibraryDir, только оттуда Android разрешает её запускать.
        jniLibs.useLegacyPackaging = true
        // Ядро кладётся байт в байт как в официальном релизе Mihomo, без обрезки.
        jniLibs.keepDebugSymbols += "**/libmihomo.so"
    }

    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "3.22.1"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}

// У каждой архитектуры свой versionCode, чтобы APK обновлялись поверх друг друга.
val abiCodes = mapOf("armeabi-v7a" to 1, "arm64-v8a" to 2, "x86_64" to 3)
androidComponents {
    onVariants { variant ->
        variant.outputs.forEach { output ->
            val abi = output.filters.find { it.filterType == com.android.build.api.variant.FilterConfiguration.FilterType.ABI }?.identifier
            val code = abiCodes[abi] ?: 0
            output.versionCode.set(appVersionCode * 10 + code)
        }
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2025.12.01")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui-tooling-preview")
    debugImplementation("androidx.compose.ui:ui-tooling")

    implementation("androidx.core:core-ktx:1.17.0")
    implementation("androidx.activity:activity-compose:1.11.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.4")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.4")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("org.snakeyaml:snakeyaml-engine:2.8")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
