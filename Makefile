.PHONY: deb release install lint check icons uninstall clean help

PKG := motion-player

help:
	@echo "Targets:"
	@echo "  deb       Build a development .deb (Recommends Pi libs)"
	@echo "  release   Build a release .deb (Depends on Pi libs)"
	@echo "  install   Install the most recently built .deb"
	@echo "  lint      Syntax-check scripts and Python files"
	@echo "  check     Run pytest suite"
	@echo "  icons     Regenerate icon sizes from packaging/make_icon.py"
	@echo "  uninstall Remove the installed package"
	@echo "  clean     Remove build artifacts"

deb:
	packaging/build_deb.sh

release:
	STRICT_DEPS=1 packaging/build_deb.sh

install:
	@DEB="$$(ls -t ./$(PKG)_*.deb | head -n1)"; \
	echo "Installing $$DEB"; \
	sudo apt install -y "$$DEB"

lint:
	find src tests packaging -name '*.py' -exec python3 -m py_compile {} +
	bash -n packaging/build_deb.sh
	bash -n packaging/motion-player-toggle
	bash -n packaging/motion-player-media
	bash -n packaging/motion-player-reverse
	bash -n packaging/motion-player-install-deb
	bash -n scripts/bootstrap_pi.sh
	bash -n scripts/update.sh
	bash -n scripts/status.sh
	@if command -v desktop-file-validate >/dev/null 2>&1; then \
		desktop-file-validate packaging/motion-player.desktop; \
	else \
		echo "desktop-file-validate not installed; skipping .desktop validation"; \
	fi

check:
	python3 -m pytest tests/ -v

icons:
	python3 packaging/make_icon.py

uninstall:
	sudo apt remove $(PKG)

clean:
	rm -f $(PKG)_*.deb
	find src tests -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find src tests -name '*.pyc' -delete 2>/dev/null || true
