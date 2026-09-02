.PHONY: test example
# Run the tests
test:
	python3 -m unittest

# Fix the /example monorepo
fix-example:
	rm -rf example/.git fixed
	cd example && git init -q && git add -A && \
	  git -c user.name=Example -c user.email=example@localhost \
	      commit -qm "create example monorepo"
	./fixmonorepo.py fix example -o fixed
	rm -rf example/.git

# Undo the fix of /example monorepo. Needs the repositories fix-example
# creates, so it runs that first.
ruin-example-fix:
	rm -rf fixed/ruined
	cd fixed && ./ruin.sh
	find example fixed -name .git -type d -prune -exec rm -rf {} +
