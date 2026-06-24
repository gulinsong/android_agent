plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.openclaw.chitchat"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.openclaw.chitchat"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        // 鉴权：从 ~/.gradle/gradle.properties 或 -P 读，不硬编码真实值入库
        buildConfigField("String", "DOUBAO_APP_ID", "\"${project.findProperty("doubaoAppId") ?: ""}\"")
        buildConfigField("String", "DOUBAO_ACCESS_KEY", "\"${project.findProperty("doubaoAccessKey") ?: ""}\"")
    }

    buildFeatures { buildConfig = true }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    kotlinOptions { jvmTarget = "11" }
}

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.google.code.gson:gson:2.10.1")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.6.2")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.6.2")
    implementation("com.google.android.material:material:1.9.0")
    testImplementation("junit:junit:4.13.2")
}
