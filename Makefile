.PHONY: setup backend frontend test check doctor package

setup:
	bash scripts/setup_debian.sh

backend:
	bash scripts/run_backend.sh

frontend:
	bash scripts/run_frontend.sh

test:
	bash scripts/test.sh

check:
	bash scripts/check.sh

doctor:
	python3 scripts/doctor.py

package:
	bash scripts/package_source.sh
