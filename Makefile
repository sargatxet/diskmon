PREFIX ?= $(HOME)/.local
BINDIR := $(PREFIX)/bin
REPO := $(shell pwd)

.PHONY: help install uninstall test scan serve

help:
	@echo "make install          Instala el comando en $(BINDIR)/diskmon (enlace simbólico)"
	@echo "make install-systemd  Instala las unidades de usuario de systemd"
	@echo "make test             Ejecuta la suite de tests"
	@echo "make scan             Analiza los discos ahora"
	@echo "make serve            Arranca el dashboard web"
	@echo "make uninstall        Elimina el enlace del comando"

install:
	mkdir -p "$(BINDIR)"
	ln -sf "$(REPO)/bin/diskmon" "$(BINDIR)/diskmon"
	@echo "Instalado: $(BINDIR)/diskmon"
	@echo "Asegúrate de que $(BINDIR) está en PATH."

uninstall:
	rm -f "$(BINDIR)/diskmon"

install-systemd: install
	mkdir -p "$(HOME)/.config/systemd/user"
	cp systemd/diskmon.service systemd/diskmon.timer systemd/diskmon-web.service \
		"$(HOME)/.config/systemd/user/"
	systemctl --user daemon-reload
	@echo "Unidades instaladas en $(HOME)/.config/systemd/user/"
	@echo "Activa el análisis periódico con: systemctl --user enable --now diskmon.timer"

test:
	python3 -m pytest

scan:
	./bin/diskmon scan

serve:
	./bin/diskmon serve
