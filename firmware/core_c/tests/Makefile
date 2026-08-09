CC ?= cc
CFLAGS ?= -std=c99 -Wall -Wextra -O2 -I../include
LDFLAGS ?= -lm

SRC = ../src/gk_limits.c ../src/gk_faults.c ../src/gk_safety.c ../src/gk_control.c
TEST_SRC = golden_runner.c

.PHONY: all test clean generate

all: golden_runner

generate:
	cd ../../.. && uv run python tools/generate_golden.py

golden_runner: $(SRC) $(TEST_SRC) golden_cases.inc
	$(CC) $(CFLAGS) -o $@ $(SRC) $(TEST_SRC) $(LDFLAGS)

test: golden_runner
	./golden_runner

clean:
	rm -f golden_runner
