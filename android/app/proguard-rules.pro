# JNI: имена нативных методов запускателя ядра должны сохраниться.
-keepclasseswithmembernames class com.sadness.vpn.vpn.CoreLauncher {
    native <methods>;
}
# snakeyaml-engine обращается к своим классам через отражение.
-keep class org.snakeyaml.engine.** { *; }
-dontwarn org.snakeyaml.engine.**
