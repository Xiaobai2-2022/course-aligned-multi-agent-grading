import json
from pathlib import Path

from core.log import log_info, log_success, log_warning, log_fail
from core.io import read_json


def process_rubric(
    json_path: str | Path
) -> dict:
    """
    Process Rubric JSON file.

    :param json_path: the path to the Rubric JSON file.
    :return: the processed Rubric JSON packets
    """

    path = Path(json_path)
    data = read_json(path)

    try:
        for key in (
            "tests", "requirements", "issues", "execution_policy",
            "feedback_issue_types",
        ):
            if not isinstance(data.get(key), list):
                raise ValueError(f"'{key}' must be a list.")

        scoring = data.get("scoring")
        if not isinstance(scoring, dict):
            raise ValueError("'scoring' must be an object.")

        def index_records(records, label):
            if not isinstance(records, list):
                raise ValueError(f"'{label}' must be a list.")

            indexed = {}
            for record in records:
                if not isinstance(record, dict):
                    raise ValueError(f"Each '{label}' entry must be an object.")

                record_id = record.get("id")
                if not isinstance(record_id, str) or not record_id:
                    raise ValueError(f"Each '{label}' entry needs a string ID.")

                if record_id in indexed:
                    raise ValueError(f"Duplicate ID in '{label}': {record_id}")

                indexed[record_id] = record

            return indexed

        group_index = index_records(scoring.get("groups"), "scoring.groups")
        test_index = index_records(data["tests"], "tests")
        requirement_index = index_records(data["requirements"], "requirements")
        policy_index = index_records(data["execution_policy"], "execution_policy")
        rule_index = index_records(scoring.get("rules"), "scoring.rules")

        names = [group.get("name") for group in group_index.values()]
        expected = {"Public tests", "Release tests", "Secret tests"}

        if len(names) != 3 or any(name not in expected for name in names):
            raise ValueError("Expected public, release, and secret test groups.")
        if len(set(names)) != 3:
            raise ValueError("Duplicate test group names.")

        for test_id, test in test_index.items():
            if test.get("group_id") not in group_index:
                raise ValueError(f"{test_id}: missing or unknown group_id.")

            references = test.get("requirement_ids")
            if not isinstance(references, list) or not all(
                isinstance(ref, str) for ref in references
            ):
                raise ValueError(f"{test_id}: requirement_ids must be strings.")

            unknown = set(references) - requirement_index.keys()
            if unknown:
                raise ValueError(
                    f"{test_id}: unknown requirements: {sorted(unknown)}"
                )

        known_ids = (
            group_index.keys() | test_index.keys()
            | requirement_index.keys() | policy_index.keys()
        )

        for rule_id, rule in rule_index.items():
            targets = rule.get("applies_to")
            if not isinstance(targets, list) or not all(
                isinstance(target, str) for target in targets
            ):
                raise ValueError(f"{rule_id}: applies_to must be a list of IDs.")

            unknown = set(targets) - known_ids
            if unknown:
                raise ValueError(
                    f"{rule_id}: unknown targets: {sorted(unknown)}"
                )

        shared = {
            key: value
            for key, value in data.items()
            if key not in {"tests", "scoring"}
        }

        packets = {}

        for group_id, group in group_index.items():
            tests = [
                test for test in data["tests"]
                if test["group_id"] == group_id
            ]
            scope = {group_id, *(test["id"] for test in tests)}

            if not tests:
                log_warning(f"{group['name']} contains no tests.")

            packets[group["name"]] = {
                **shared,
                "tests": tests,
                "scoring": group,
                "scoring_rules": [
                    rule for rule in rule_index.values()
                    if not rule["applies_to"]
                    or scope.intersection(rule["applies_to"])
                ],
            }

    except json.JSONDecodeError as exc:
        log_fail(
            f"Invalid JSON at line {exc.lineno}, "
            f"column {exc.colno}: {exc.msg}"
        )
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        log_fail(f"Failed to process rubric '{path}': {exc}")
        raise

    if data.get("review_required"):
        log_warning("The rubric is marked as requiring review.")

    log_success(
        f"Processed {len(test_index)} tests into {len(packets)} groups."
    )
    return packets



def load_rubric(
    json_path: str | Path
) -> dict:
    """
    Load the rubric json file

    :param json_path: the path to the rubric json file
    :return: the given packet
    """

    packets = process_rubric(json_path)

    log_info("Building rubric lookup.")

    try:
        expected_groups = {"Public tests", "Release tests", "Secret tests"}

        if not isinstance(packets, dict):
            raise ValueError("Processed rubric must be a dictionary.")

        if set(packets) != expected_groups:
            raise ValueError(
                "Expected exactly Public tests, Release tests, and Secret tests."
            )

        for name, packet in packets.items():
            if not isinstance(packet, dict):
                raise ValueError(f"'{name}' must contain a dictionary.")

            for key, expected_type in (
                ("tests", list),
                ("scoring", dict),
                ("scoring_rules", list),
            ):
                if not isinstance(packet.get(key), expected_type):
                    raise ValueError(
                        f"'{name}.{key}' must be a {expected_type.__name__}."
                    )

        shared = packets["Public tests"]
        shared_keys = (
            "requirements",
            "issues",
            "feedback_issue_types",
            "execution_policy",
        )

        for key in shared_keys:
            if not isinstance(shared.get(key), list):
                raise ValueError(f"'{key}' must be a list.")

            for name, packet in packets.items():
                if packet.get(key) != shared[key]:
                    raise ValueError(
                        f"'{key}' differs between Public tests and {name}."
                    )

        group_keys = {
            "Public tests": "public_tests",
            "Release tests": "release_tests",
            "Secret tests": "secret_tests",
        }

        result = {
            **{
                group_keys[name]: packet["tests"]
                for name, packet in packets.items()
            },
            "scoring": {
                group_keys[name]: {
                    **packet["scoring"],
                    "rules": packet["scoring_rules"],
                }
                for name, packet in packets.items()
            },
            **{key: shared[key] for key in shared_keys},
        }

    except ValueError as exc:
        log_fail(f"Failed to build rubric lookup: {exc}")
        raise

    log_success("Rubric lookup created successfully.")
    return result
