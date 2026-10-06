from __future__ import annotations

import json
import math
import re

from pathlib import Path
from jsonschema import Draft202012Validator

from core.log import log_info, log_success, log_warning, log_fail

MAX_BYTES = 10 * 1024 * 1024

class DesignError(ValueError):
    pass

def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DesignError(f'Duplicate JSON key: {key!r}')
        result[key] = value
    return result

def reject_constant(value):
    raise DesignError(f'Invalid JSON numeric constant: {value}')

def load_json(path):
    with Path(path).open('rb') as f:
        raw = f.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise DesignError('JSON exceeds the 10 MiB ingestion limit')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object,
                      parse_constant=reject_constant)

def check_json_values(value, depth=0):
    if depth > 100:
        raise DesignError('JSON exceeds the nesting limit of 100')
    if isinstance(value, str):
        if '\x00' in value or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise DesignError('JSON contains NUL or an unpaired Unicode surrogate')
    elif isinstance(value, float) and not math.isfinite(value):
        raise DesignError('JSON contains a non-finite or overflowing number')
    elif isinstance(value, dict):
        for k, v in value.items():
            check_json_values(k, depth+1)
            check_json_values(v, depth+1)
    elif isinstance(value, list):
        for v in value:
            check_json_values(v, depth+1)


def _validate_design(data, schema):
    check_json_values(data)
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema).iter_errors(data))
    if errors:
        locations = [f"/{'/'.join(map(str,e.absolute_path))}: {e.validator} constraint failed" for e in errors[:20]]
        raise DesignError('\n'.join(locations))
    def need(condition, message):
        if not condition:
            raise DesignError(message)
    def index(records, key, label):
        result = {r[key]: r for r in records}
        need(len(result) == len(records), f'Duplicate {label}')
        return result
    def subset(values, valid, label):
        need(set(values) <= set(valid), f'Unresolved reference in {label}')
    sources = index(data['sources'], 'id', 'source IDs')
    reqs = index(data['requirements'], 'id', 'requirement IDs')
    dims = index(data['testing_dimensions'], 'category', 'dimension categories')
    reviews = index(data['human_review_requests'], 'id', 'review IDs')
    records = []
    for t in data['prerequisite_checks']:
        records.append(t)
        need(t['suite']=='prerequisite' and t['difficulty']=='not_applicable' and re.fullmatch(r'PRE\d{3,}',t['id']), 'Invalid prerequisite suite/difficulty/ID')
    for suite, prefix, difficulty in [('public','PUB','easy'),('release','REL','medium'),('private','PRI','difficult')]:
        for key, suffix in [('deterministic_tests',''),('randomized_test_families','-R')]:
            for t in data['test_suites'][suite][key]:
                records.append(t)
                need(t['suite'] == suite and re.fullmatch(prefix + suffix + r'\d{3,}', t['id']),
                     f'Invalid suite/ID: {t["id"]}')
                need(t['difficulty'] in {'easy', 'medium', 'difficult'},
                     f'Invalid test difficulty: {t["id"]}')
                if t['difficulty'] != difficulty:
                    log_warning(
                        f"{t['id']}: suite '{suite}' normally uses difficulty "
                        f"'{difficulty}', but received '{t['difficulty']}'. "
                        "Continuing validation; original value preserved."
                    )
    tests = index(records, 'id', 'test IDs')
    all_ids = list(sources)+list(reqs)+list(reviews)+list(tests)
    need(len(all_ids)==len(set(all_ids)), 'Record IDs must be unique across record types')
    def source_refs(refs):
        for r in refs:
            need(r['source_id'] in sources, 'Unknown source_id')
            need(bool((r['location'] or '').strip() or (r['excerpt'] or '').strip()), 'Source reference needs a location or excerpt')
    for r in reqs.values():
        source_refs(r['source_refs'])
        need((r['implication_explanation'] is None) if r['basis']=='explicit' else bool((r['implication_explanation'] or '').strip()), f'Invalid implication explanation: {r["id"]}')
    for d in dims.values():
        subset(d['requirement_ids'],reqs,'dimension requirements')
        need(d['status']!='applicable' or bool(d['requirement_ids']), 'Applicable dimension needs requirements')
    for collection in ['ambiguities','coverage_gaps']:
        for item in data[collection]:
            subset(item['requirement_ids'],reqs,collection)
            subset(item['test_ids'],tests,collection)
            subset(item['human_review_ids'],reviews,collection)
    for t in records:
        subset(t['requirement_ids'],reqs,t['id'])
        subset([t['primary_category']]+t['secondary_categories'],dims,t['id'])
        need(t['primary_category'] not in t['secondary_categories'], 'Primary category repeated as secondary')
        subset(t['human_review_ids'],reviews,t['id'])
        subset(t.get('dependencies',[]),tests,t['id'])
        need(t['id'] not in t.get('dependencies',[]), 'Self dependency')
        if t['readiness']=='ready':
            need(t['blocking_information'] is None, 'Ready test has blocking information')
            keys = ['oracle','assertions','generation_strategy','case_count'] if 'oracle' in t else ['expected_result','comparison_rule','oracle_basis']
            need(all(t[k] not in (None,'',[],{}) for k in keys), f'Ready test lacks oracle/inspection/generator information: {t["id"]}')
            need(all(tests[x]['readiness']=='ready' for x in t.get('dependencies',[])), 'Ready test depends on blocked test')
        else:
            need(bool((t['blocking_information'] or '').strip()), 'Blocked test lacks explanation')
    visiting, done = set(), set()
    def visit(tid):
        need(tid not in visiting, 'Dependency cycle')
        if tid in done:
            return
        visiting.add(tid)
        for dep in tests[tid].get('dependencies',[]):
            visit(dep)
        visiting.remove(tid)
        done.add(tid)
    for tid in tests:
        visit(tid)
    pending = False
    for rid,r in reviews.items():
        need(re.fullmatch(r'HR\d{3,}',rid), 'Invalid review ID')
        source_refs(r['source_refs'])
        subset(r['affected_requirement_ids'],reqs,rid)
        subset(r['affected_test_ids'],tests,rid)
        subset(r['affected_dimensions'],dims,rid)
        if r['status']=='resolved':
            need(r['resolution'] is not None, 'Resolved review lacks resolution')
            source_refs(r['resolution']['source_refs'])
            continue
        pending = True
        need(r['resolution'] is None, 'Pending review has a resolution')
        if r['blocking']:
            affected = set(r['affected_test_ids'])
            for t in records:
                if set(t['requirement_ids']) & set(r['affected_requirement_ids']) or set([t['primary_category']]+t['secondary_categories']) & set(r['affected_dimensions']) or rid in t['human_review_ids']:
                    affected.add(t['id'])
            while True:
                expanded = affected | {t['id'] for t in records if set(t.get('dependencies',[])) & affected}
                if expanded == affected:
                    break
                affected = expanded
            for tid in affected:
                need(tests[tid]['readiness']=='blocked' and rid in tests[tid]['human_review_ids'], f'Blocking review not propagated: {rid} -> {tid}')
    need(data['human_review_required']==pending, 'human_review_required disagrees with pending reviews')
    coverage = index(data['coverage_matrix'],'requirement_id','coverage requirements')
    need(set(coverage)==set(reqs),'Coverage must include exactly every requirement')
    for rid,row in coverage.items():
        expected = {t['id'] for t in records if rid in t['requirement_ids']}
        need(set(row['test_ids'])==expected, f'Coverage mismatch: {rid}')
        for state in ['ready','blocked']:
            need(set(row[state+'_test_ids'])=={x for x in expected if tests[x]['readiness']==state}, f'{state} coverage mismatch: {rid}')
        if not expected:
            need(any(rid in g['requirement_ids'] for g in data['coverage_gaps']), f'Uncovered requirement lacks gap: {rid}')
    if data['status']=='complete':
        need(bool(records), 'Complete design has no tests')
        need(all(t['readiness']=='ready' for t in records), 'Complete design contains blocked tests')
        need(not any(r['status']=='pending' and r['blocking'] for r in reviews.values()), 'Complete design contains blocking review')
    if data['status']=='blocked':
        need(not any(t['readiness']=='ready' for t in records), 'Blocked design contains ready tests; use partial')
    if data['status']=='partial':
        need(bool(records), 'Partial design has no test records; use blocked')
    doc=data['document']
    need(doc['page_count'] is not None or not doc['pages_processed'], 'Unknown page count requires empty pages_processed')
    if doc['page_count'] is not None:
        need(all(x<=doc['page_count'] for x in doc['pages_processed']), 'Page number exceeds page_count')
        if doc['extraction_complete']:
            need(len(doc['pages_processed'])==doc['page_count'], 'Extraction marked complete with unread pages')
    return data



DEFAULT_SCHEMA = json.loads('{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object","properties":{"schema_version":{"const":"1.1"},"document":{"type":"object","properties":{"title":{"type":["string","null"]},"course":{"type":["string","null"]},"assignment_name":{"type":["string","null"]},"page_count":{"type":["integer","null"],"minimum":1},"pages_processed":{"type":"array","items":{"type":"integer","minimum":1},"uniqueItems":true},"extraction_complete":{"type":"boolean"}},"required":["title","course","assignment_name","page_count","pages_processed","extraction_complete"],"additionalProperties":false},"status":{"enum":["complete","partial","blocked"]},"sources":{"type":"array","items":{"type":"object","properties":{"id":{"type":"string","minLength":1},"name":{"type":"string","minLength":1},"role":{"type":"string","minLength":1},"reading_status":{"enum":["complete","partial","unreadable","missing"]},"notes":{"type":["string","null"]}},"required":["id","name","role","reading_status","notes"],"additionalProperties":false}},"question_analysis":{"type":"object"},"requirements":{"type":"array","items":{"type":"object","properties":{"id":{"type":"string","minLength":1},"description":{"type":"string","minLength":1},"source_refs":{"type":"array","items":{"type":"object","properties":{"source_id":{"type":"string","minLength":1},"location":{"type":["string","null"]},"excerpt":{"type":["string","null"]}},"required":["source_id","location","excerpt"],"additionalProperties":false},"minItems":1},"basis":{"enum":["explicit","logically_implied"]},"implication_explanation":{"type":["string","null"]},"verification_methods":{"type":"array","items":{"enum":["build","structure_check","runtime","static_analysis","manual_review"]},"minItems":1,"uniqueItems":true}},"required":["id","description","source_refs","basis","implication_explanation","verification_methods"],"additionalProperties":false}},"testing_dimensions":{"type":"array","items":{"type":"object","properties":{"category":{"type":"string","pattern":"^[a-z][a-z0-9_]*$"},"description":{"type":"string","minLength":1},"status":{"enum":["applicable","unclear"]},"requirement_ids":{"type":"array","items":{"type":"string","minLength":1},"uniqueItems":true},"scenarios":{"type":"array","items":{"type":"string","minLength":1}},"verification_methods":{"type":"array","items":{"enum":["build","structure_check","runtime","static_analysis","manual_review"]},"minItems":1,"uniqueItems":true},"justification":{"type":"string","minLength":1}},"required":["category","description","status","requirement_ids","scenarios","verification_methods","justification"],"additionalProperties":false}},"testing_configuration":{"type":"object"},"prerequisite_checks":{"type":"array","items":{"$ref":"#/$defs/deterministic_test"}},"test_suites":{"type":"object","properties":{"public":{"$ref":"#/$defs/suite"},"release":{"$ref":"#/$defs/suite"},"private":{"$ref":"#/$defs/suite"}},"required":["public","release","private"],"additionalProperties":false},"coverage_matrix":{"type":"array","items":{"type":"object","properties":{"requirement_id":{"type":"string","minLength":1},"test_ids":{"type":"array","items":{"type":"string","minLength":1},"uniqueItems":true},"ready_test_ids":{"type":"array","items":{"type":"string","minLength":1},"uniqueItems":true},"blocked_test_ids":{"type":"array","items":{"type":"string","minLength":1},"uniqueItems":true},"notes":{"type":["string","null"]}},"required":["requirement_id","test_ids","ready_test_ids","blocked_test_ids","notes"],"additionalProperties":false}},"ambiguities":{"type":"array","items":{"type":"object","properties":{"description":{"type":"string","minLength":1},"requirement_ids":{"type":"array","items":{"type":"string","minLength":1},"uniqueItems":true},"test_ids":{"type":"array","items":{"type":"string","minLength":1},"uniqueItems":true},"human_review_ids":{"type":"array","items":{"type":"string","minLength":1},"uniqueItems":true}},"required":["description","requirement_ids","test_ids","human_review_ids"],"additionalProperties":false}},"coverage_gaps":{"type":"array","items":{"type":"object","properties":{"description":{"type":"string","minLength":1},"requirement_ids":{"type":"array","items":{"type":"string","minLength":1},"uniqueItems":true},"test_ids":{"type":"array","items":{"type":"string","minLength":1},"uniqueItems":true},"human_review_ids":{"type":"array","items":{"type":"string","minLength":1},"uniqueItems":true}},"required":["description","requirement_ids","test_ids","human_review_ids"],"additionalProperties":false}},"downstream_notes":{"type":"array","items":{"type":"string","minLength":1}},"human_review_required":{"type":"boolean"},"human_review_requests":{"type":"array","items":{"type":"object","properties":{"id":{"type":"string","minLength":1},"status":{"enum":["pending","resolved"]},"reason":{"type":"string","minLength":1},"source_refs":{"type":"array","items":{"type":"object","properties":{"source_id":{"type":"string","minLength":1},"location":{"type":["string","null"]},"excerpt":{"type":["string","null"]}},"required":["source_id","location","excerpt"],"additionalProperties":false}},"affected_requirement_ids":{"type":"array","items":{"type":"string","minLength":1},"uniqueItems":true},"affected_test_ids":{"type":"array","items":{"type":"string","minLength":1},"uniqueItems":true},"affected_dimensions":{"type":"array","items":{"type":"string","minLength":1},"uniqueItems":true},"question_for_reviewer":{"type":"string","minLength":1},"options":{"type":"array","items":{"type":"string","minLength":1}},"recommended_action":{"type":["string","null"]},"blocking":{"type":"boolean"},"resolution":{"anyOf":[{"type":"null"},{"type":"object","properties":{"decision":{"type":"string","minLength":1},"source_refs":{"type":"array","items":{"type":"object","properties":{"source_id":{"type":"string","minLength":1},"location":{"type":["string","null"]},"excerpt":{"type":["string","null"]}},"required":["source_id","location","excerpt"],"additionalProperties":false},"minItems":1},"changes":{"type":"string","minLength":1}},"required":["decision","source_refs","changes"],"additionalProperties":false}]}},"required":["id","status","reason","source_refs","affected_requirement_ids","affected_test_ids","affected_dimensions","question_for_reviewer","options","recommended_action","blocking","resolution"],"additionalProperties":false}}},"required":["schema_version","document","status","sources","question_analysis","requirements","testing_dimensions","testing_configuration","prerequisite_checks","test_suites","coverage_matrix","ambiguities","coverage_gaps","downstream_notes","human_review_required","human_review_requests"],"additionalProperties":false,"$defs":{"deterministic_test":{"type":"object","properties":{"id":{"type":"string","minLength":1},"title":{"type":"string","minLength":1},"suite":{"enum":["prerequisite","public","release","private"]},"difficulty":{"enum":["not_applicable","easy","medium","difficult"]},"requirement_ids":{"type":"array","items":{"type":"string","minLength":1},"minItems":1,"uniqueItems":true},"primary_category":{"type":"string","minLength":1},"secondary_categories":{"type":"array","items":{"type":"string","minLength":1},"uniqueItems":true},"purpose":{"type":"string","minLength":1},"difficulty_reason":{"type":"string","minLength":1},"readiness":{"enum":["ready","blocked"]},"blocking_information":{"type":["string","null"]},"human_review_ids":{"type":"array","items":{"type":"string","minLength":1},"uniqueItems":true},"verification_methods":{"type":"array","items":{"enum":["build","structure_check","runtime","static_analysis","manual_review"]},"minItems":1,"uniqueItems":true},"setup":{"type":["object","array","string","null"]},"input":{"type":["object","array","string","null"]},"expected_result":{"type":["object","array","string","null","number","boolean"]},"comparison_rule":{"type":["object","array","string","null"]},"oracle_basis":{"type":["object","array","string","null"]},"targeted_mistake":{"type":"string","minLength":1},"dependencies":{"type":"array","items":{"type":"string","minLength":1},"uniqueItems":true}},"required":["id","title","suite","difficulty","requirement_ids","primary_category","secondary_categories","purpose","difficulty_reason","readiness","blocking_information","human_review_ids","verification_methods","setup","input","expected_result","comparison_rule","oracle_basis","targeted_mistake","dependencies"],"additionalProperties":false},"randomized_family":{"type":"object","properties":{"id":{"type":"string","minLength":1},"title":{"type":"string","minLength":1},"suite":{"enum":["prerequisite","public","release","private"]},"difficulty":{"enum":["not_applicable","easy","medium","difficult"]},"requirement_ids":{"type":"array","items":{"type":"string","minLength":1},"minItems":1,"uniqueItems":true},"primary_category":{"type":"string","minLength":1},"secondary_categories":{"type":"array","items":{"type":"string","minLength":1},"uniqueItems":true},"purpose":{"type":"string","minLength":1},"difficulty_reason":{"type":"string","minLength":1},"readiness":{"enum":["ready","blocked"]},"blocking_information":{"type":["string","null"]},"human_review_ids":{"type":"array","items":{"type":"string","minLength":1},"uniqueItems":true},"generated_variables":{"type":["object","array","string","null"]},"valid_domain":{"type":["object","array","string","null"]},"generation_strategy":{"type":["object","array","string","null"]},"variable_dependencies":{"type":["object","array","string","null"]},"sampling_parameters":{"type":["object","array","string","null"]},"seed_policy":{"type":["object","array","string","null"]},"oracle":{"type":["object","array","string","null"]},"assertions":{"type":["object","array","string","null"]},"state_setup_and_reset":{"type":["object","array","string","null"]},"failure_record":{"type":["object","array","string","null"]},"targeted_mistakes":{"type":["object","array","string","null"]},"case_count":{"type":["integer","null"],"minimum":1}},"required":["id","title","suite","difficulty","requirement_ids","primary_category","secondary_categories","purpose","difficulty_reason","readiness","blocking_information","human_review_ids","generated_variables","valid_domain","generation_strategy","variable_dependencies","sampling_parameters","seed_policy","oracle","assertions","state_setup_and_reset","failure_record","targeted_mistakes","case_count"],"additionalProperties":false},"suite":{"type":"object","properties":{"purpose":{"type":"string","minLength":1},"deterministic_tests":{"type":"array","items":{"$ref":"#/$defs/deterministic_test"}},"randomized_test_families":{"type":"array","items":{"$ref":"#/$defs/randomized_family"}}},"required":["purpose","deterministic_tests","randomized_test_families"],"additionalProperties":false}}}')


def validate_design(data: dict | str, schema: dict | None = None) -> dict:
    """Validate generated content and return its dictionary; log and raise on failure.

    Supply the assistant's JSON content, not the full API response envelope.
    Markdown fences are rejected rather than silently repaired.
    An optional schema dictionary can override the embedded schema.
    """
    log_info("Validating generated test design...")
    try:
        if isinstance(data, str):
            if len(data.encode("utf-8")) > MAX_BYTES:
                raise DesignError("JSON exceeds the 10 MiB ingestion limit")
            data = json.loads(data, object_pairs_hook=unique_object,
                              parse_constant=reject_constant)
        if not isinstance(data, dict):
            raise DesignError("Test design must be a dictionary or a JSON object string.")
        check_json_values(data)
        if len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_BYTES:
            raise DesignError("JSON exceeds the 10 MiB ingestion limit")
        result = _validate_design(data, DEFAULT_SCHEMA if schema is None else schema)
    except (ValueError, TypeError, OSError, RecursionError) as exc:
        for line in str(exc).splitlines():
            log_fail(f"Validation error: {line}")
        raise
    except Exception as exc:
        log_fail(f"Validation could not complete: {type(exc).__name__}")
        raise
    log_success("JSON structure and reference validation passed.")
    if result["status"] != "complete" or result["human_review_required"]:
        log_warning(
            f"Design status: {result['status']}; "
            f"human review required: {result['human_review_required']}. "
            "Validation does not constitute grading approval."
        )
    return result
