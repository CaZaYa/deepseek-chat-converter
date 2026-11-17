plugins {
    id("com.android.application")
}

val generatedWebAssets = layout.buildDirectory.dir("generated/web-assets")

val copyWebAssets by tasks.registering(Copy::class) {
    from(rootProject.file("../docs/mobile")) {
        exclude("**/*.map")
    }
    into(generatedWebAssets.map { it.dir("mobile") })
}

android {
    namespace = "com.cazaya.deepseek2any"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.cazaya.deepseek2any"
        minSdk = 29
        targetSdk = 35
        versionCode = 117
        versionName = "1.1.7"
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

    sourceSets["main"].assets.srcDir(generatedWebAssets)

    lint {
        abortOnError = false
    }
}

tasks.named("preBuild").configure {
    dependsOn(copyWebAssets)
}

dependencies {
    implementation("androidx.webkit:webkit:1.12.1")
}
