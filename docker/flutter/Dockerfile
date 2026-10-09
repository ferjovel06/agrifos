# Linux amd64 only. Update the archive, checksums and version assertions together.
# Flutter metadata: https://storage.googleapis.com/flutter_infra_release/releases/releases_linux.json
# JDK image: https://github.com/docker-library/official-images/blob/master/library/eclipse-temurin
FROM eclipse-temurin:17.0.20.1_1-jdk-noble@sha256:fb79620c3f6ee8f1c7530a8dc4fd49e3b410bcef037694ad4858a1553bac4170 AS tools

ARG TARGETARCH
ARG FLUTTER_UID=1000
ARG FLUTTER_GID=1000

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN test "$TARGETARCH" = amd64 \
    && test "$FLUTTER_UID" -ge 1000 && test "$FLUTTER_GID" -ge 1000
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    apt-get update \
    && apt-get install --no-install-recommends -y \
        ca-certificates curl git libglu1-mesa libstdc++6 fontconfig \
        python3 rsync unzip util-linux xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Noble can provide a default user with UID 1000. Replace that account inside
# this image, keeping the host's mapped UID/GID away from privileged accounts.
RUN if getent passwd "$FLUTTER_UID" >/dev/null; then \
        existing_user="$(getent passwd "$FLUTTER_UID" | cut -d: -f1)"; \
        userdel "$existing_user"; fi \
    && if getent group "$FLUTTER_GID" >/dev/null; then \
        existing_group="$(getent group "$FLUTTER_GID" | cut -d: -f1)"; \
        groupmod --new-name flutter "$existing_group"; \
       else groupadd --gid "$FLUTTER_GID" flutter; fi \
    && useradd --uid "$FLUTTER_UID" --gid "$FLUTTER_GID" \
        --create-home --home-dir /home/flutter flutter \
    && install -d -o flutter -g flutter /opt/flutter /workspace \
        /home/flutter/.pub-cache /home/flutter/.gradle /opt/android-sdk /artifacts

RUN curl --fail --location --retry 2 --output /tmp/flutter.tar.xz \
        https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_3.44.9-stable.tar.xz \
    && echo 'a9120fa4a01048bdef438ddc3a2d4b7389662ea98a95db86eeaf10382bc4efcb  /tmp/flutter.tar.xz' | sha256sum --check --strict \
    && tar --extract --xz --file /tmp/flutter.tar.xz --directory /opt \
    && rm /tmp/flutter.tar.xz \
    && chown -R flutter:flutter /opt/flutter

ENV HOME=/home/flutter \
    PATH=/opt/flutter/bin:/opt/android-sdk/cmdline-tools/22.0/bin:/opt/android-sdk/platform-tools:$PATH \
    PUB_CACHE=/home/flutter/.pub-cache \
    GRADLE_USER_HOME=/home/flutter/.gradle \
    ANDROID_HOME=/opt/android-sdk \
    ANDROID_SDK_ROOT=/opt/android-sdk \
    ANDROID_USER_HOME=/workspace/.android \
    CI=true \
    FLUTTER_SUPPRESS_ANALYTICS=true \
    DART_SUPPRESS_ANALYTICS=true

COPY --chmod=0755 entrypoint.sh /usr/local/bin/agrifos-flutter
COPY client.env.example /opt/agrifos/client.env.example
USER flutter:flutter
WORKDIR /workspace

RUN flutter --disable-analytics \
    && dart --disable-analytics \
    && flutter precache --linux --no-android --no-ios --no-web --no-macos --no-windows --no-fuchsia \
    && flutter --version --machine > /tmp/flutter-version.json \
    && python3 -c 'import json; v=json.load(open("/tmp/flutter-version.json")); assert v["frameworkVersion"] == "3.44.9", v; assert v["dartSdkVersion"] == "3.12.2", v' \
    && rm /tmp/flutter-version.json

ENTRYPOINT ["/usr/local/bin/agrifos-flutter"]
CMD ["version"]

# Download SDK tooling only. No SDK license is accepted, and no licensed
# platform/build-tools/NDK package is installed during image construction.
FROM tools AS android
USER root
# Stable tools 22.0, verified against Google's repository XML and Studio table:
# https://dl.google.com/android/repository/repository2-3.xml
# https://developer.android.com/studio#command-line-tools-only
RUN curl --fail --location --retry 2 --output /tmp/android-cmdline.zip \
        https://dl.google.com/android/repository/commandlinetools-linux-15859902_latest.zip \
    && echo '4e4c464f145a7512b57d088ac6c278c03c9eea610886b35a5e0804e74eedf583  /tmp/android-cmdline.zip' | sha256sum --check --strict \
    && mkdir -p /opt/android-tooling \
    && unzip -q /tmp/android-cmdline.zip -d /opt/android-tooling \
    && mv /opt/android-tooling/cmdline-tools /opt/android-tooling/22.0 \
    && rm /tmp/android-cmdline.zip
# The compressed Platform Tools archive is provisioned only after license
# review. SHA256 was computed after matching Google's repository XML SHA1
# 477254aa5f903c15cf51001717bdf347fb6b53e0 for this exact versioned archive.
RUN curl --fail --location --retry 2 --output /opt/android-tooling/platform-tools.zip \
        https://dl.google.com/android/repository/platform-tools_r37.0.1-linux.zip \
    && echo 'd230f13842f60f782a8645f9c813f8f845bf36089ea7289f28c48f17979313f1  /opt/android-tooling/platform-tools.zip' | sha256sum --check --strict
USER flutter:flutter
RUN flutter precache --android --no-ios --no-web --no-macos --no-windows --no-linux --no-fuchsia
CMD ["version"]
