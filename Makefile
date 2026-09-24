# Release builds. Outputs go to dist/.
FLATPAK_MANIFEST := packaging/flatpak/io.github.dengobey.Pickit.yml
APP_ID := io.github.dengobey.Pickit

.PHONY: all flatpak appimage clean

all: flatpak appimage

# Needs: flatpak install --user flathub org.gnome.Sdk//51 org.flatpak.Builder
flatpak:
	cd packaging/flatpak && flatpak run org.flatpak.Builder --user --force-clean --disable-rofiles-fuse \
	  --state-dir=$(CURDIR)/build/fp-state --repo=$(CURDIR)/build/fp-repo $(CURDIR)/build/fp-build \
	  $(notdir $(FLATPAK_MANIFEST))
	mkdir -p dist
	flatpak build-bundle --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo \
	  build/fp-repo dist/Pickit.flatpak $(APP_ID)

appimage:
	packaging/appimage/build-appimage.sh

clean:
	rm -rf build dist
