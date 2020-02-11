
KAFKA_VERSION := $(shell awk '/version:/ {print $$2}' snap/snapcraft.yaml | head -1 | sed "s/'//g")

.PHONY: all
all: lint charm

.PHONY: lint
lint:
	flake8 --ignore=E121,E123,E126,E226,E24,E704,E265 charm/kafka

.PHONY: charm
charm: charm/builds/kafka

charm/builds/kafka:
	$(MAKE) -C charm/kafka

.PHONY: clean
clean: clean-charm

.PHONY: clean-charm
clean-charm:
	$(RM) -r charm/builds charm/deps
