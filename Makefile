# ncdu-clean - build and install (used by the Debian package as well)
PREFIX ?= /usr
DESTDIR ?=
LANGS := $(patsubst po/%.po,%,$(wildcard po/*.po))
MOS := $(LANGS:%=locale/%/LC_MESSAGES/ncdu-clean.mo)

.PHONY: all install check pot clean

all: $(MOS)

locale/%/LC_MESSAGES/ncdu-clean.mo: po/%.po
	mkdir -p $(dir $@)
	msgfmt --check -o $@ $<

install: all
	install -D -m 0755 ncdu-clean $(DESTDIR)$(PREFIX)/bin/ncdu-clean
	install -D -m 0644 man/ncdu-clean.1 $(DESTDIR)$(PREFIX)/share/man/man1/ncdu-clean.1
	for l in $(LANGS); do \
	  install -D -m 0644 locale/$$l/LC_MESSAGES/ncdu-clean.mo \
	    $(DESTDIR)$(PREFIX)/share/locale/$$l/LC_MESSAGES/ncdu-clean.mo || exit 1; \
	done

# Smoke test: needs neither ncdu nor write access outside the build directory.
check:
	python3 -c "import ast; ast.parse(open('ncdu-clean').read())"
	python3 ncdu-clean --version
	python3 ncdu-clean list tests/sample.json | grep -q app.log
	sh tests/suggest.sh

# Refresh the translation template and merge it into each catalogue.
pot:
	xgettext -L Python --from-code=UTF-8 --add-comments -k_ -kngettext:1,2 \
	  -kpgettext:1c,2 --package-name=ncdu-clean -o po/ncdu-clean.pot ncdu-clean
	for f in po/*.po; do msgmerge --update --backup=none $$f po/ncdu-clean.pot; done

clean:
	rm -rf locale
