"""Read-only staged benchmark admission report; never activates a registry."""
import argparse
import json
import re
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse

CLASSIFICATION_SCOPE = set("NVDA ASML V LLY AJG VTR PG NEE NVS SHW RHI WDFC GEF NOG AIN TDAY NNBR JOUT PETS SAP SONY TM RY BHP UL EQNR".split())
HISTORICAL_SCOPE = set("ACNB ANGO BGS CAL CCBG FRPH HBB MLR MTRX NATH NGS PLOW RELL RGR SGC SWBI USNA UTMD VLGEA".split())
HOLDOUTS = set("AON AJG DTE PCAR ODFL VTR ENS OGS KBR AVT VNT RHI BKH HBB VLGEA SENEA ANGO UTMD USNA MTRX".split())
LEGACY_STATUS = "existing_registry_metadata_reusable_not_freshly_source_adjudicated"
PRIMARY_STATUSES = {"verified_primary", "primary_filing_verified", "adjudicated_from_primary", "verified_explicit_primary", "primary_issuer_release_verified"}
SECTOR_STATUSES = {"analyst_mapping_from_primary_business_evidence", "analyst_mapping_from_primary_business", "analyst_mapped_from_primary_business_description"}
SECTORS = {"Energy", "Materials", "Industrials", "Consumer Discretionary", "Consumer Staples", "Health Care", "Financials", "Information Technology", "Communication Services", "Utilities", "Real Estate"}

def read(path):
    return json.loads(path.read_text())

def unique_rows(rows, key="ticker"):
    result = {}
    for row in rows:
        ticker = row[key]
        if ticker in result:
            raise ValueError(f"Duplicate {key}: {ticker}")
        result[ticker] = row
    return result

def is_url(value):
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"https", "http"} and bool(parsed.netloc)

def source_resolves(field, row, document):
    ref = field.get("source_ref")
    if field.get("status") == LEGACY_STATUS:
        return ref == "validation/issuer_registry.v1.json"
    if is_url(ref):
        return True
    for sources in (row.get("sources", []), document.get("sources", [])):
        if isinstance(sources, dict):
            sources = [dict(v, id=k) if isinstance(v, dict) else {"id": k, "url": v} for k, v in sources.items()]
        for source in sources:
            if isinstance(source, dict) and ref and ref in (source.get("id"), source.get("source_id")) and is_url(source.get("url", source.get("source_url"))):
                return True
    return False

def valid_metadata(name, field, row, document):
    if not isinstance(field, dict):
        return False
    value, status = field.get("value"), field.get("status")
    allowed = SECTOR_STATUSES if name == "sector" else PRIMARY_STATUSES
    if status not in allowed | {LEGACY_STATUS} or not source_resolves(field, row, document):
        return False
    if name == "domicile":
        # ISO countries represented by this frozen cohort; expand only on review.
        return value in {"US", "IE", "DE", "JP", "GB", "NL", "CH", "CA", "AU", "TW", "NO"}
    if name == "reporting_basis":
        return value in {"US_GAAP", "IFRS"}
    return value in SECTORS

def classification_eligible(ticker, candidate, adjudication, cap):
    tier = candidate["proposed_size_tier"]
    if ticker in CLASSIFICATION_SCOPE:
        return adjudication.get("tier_eligible", adjudication.get("admitted_tier_evidence")) is True and adjudication.get("tier") == tier
    if cap.get("tier_from_historical_row") != tier:
        return False
    if ticker in HISTORICAL_SCOPE:
        return cap.get("cap_decision") == "approved_historical_row_precedence" and cap.get("selected_value_usd") == cap.get("historical_row", {}).get("normalized_usd") and bool(cap.get("selected_value_usd"))
    return cap.get("cap_decision") == "equal_displayed_values" and cap.get("conflict_unresolved") is False and cap.get("tier_from_summary") == tier and cap.get("summary", {}).get("normalized_usd") == cap.get("historical_row", {}).get("normalized_usd") and bool(cap.get("summary", {}).get("normalized_usd"))

def build_readiness(proposal_dir):
    """Return readiness from local evidence; do not mutate any input artifacts."""
    p = Path(proposal_dir)
    q = p / "reconciliation"
    plan=read(p/'candidate_plan.json');meta={r['ticker']:r for r in read(q/'metadata_admission_audit.json')['rows']}
    dom=read(q/'classification_domestic_adjudication.json');intl=read(q/'international_classification_admission.json')
    classified={r['ticker']:(r,'classification_domestic_adjudication.json')for r in dom['rows']}
    classified.update({r['ticker']:(r,'international_classification_admission.json')for r in intl['rows']})
    supplemental={}
    origins={}
    cap=unique_rows(read(q/'cap_value_review.json')['rows'])
    approval=read(q/'approved_classification_only.json')
    prior=read(q/'approved_historical_precedence.json')
    if approval.get('status')!='approved_by_user' or set(approval.get('scope_tickers',[]))!=CLASSIFICATION_SCOPE or len(approval.get('scope_tickers',[]))!=26: raise ValueError('classification approval scope changed')
    if prior.get('status')!='approved_and_applied' or set(prior.get('scope_tickers',[]))!=HISTORICAL_SCOPE or len(prior.get('scope_tickers',[]))!=19: raise ValueError('historical approval scope changed')
    unique_rows(plan['candidates'], 'ticker_candidate')
    unique_rows(read(q/'metadata_admission_audit.json')['rows'])
    unique_rows(dom['rows']+intl['rows'])
    for batch in sorted(q.glob('metadata_completion_batch*.json')):
     for r in read(batch)['rows']:
      if r['ticker'] in supplemental: raise ValueError('Duplicate supplemental ticker: '+r['ticker'])
      supplemental[r['ticker']]=(r,batch.name)
      origins[r['ticker']]=read(batch)
    rows=[]
    for c in plan['candidates']:
     t=c['ticker_candidate'];m=meta[t];x,ref=classified.get(t,({},'cap_value_review.json'))
     eligible=classification_eligible(t,c,x,cap.get(t,{}))
     fields=m['metadata_fields'].copy()
     # Explicitly adjudicated metadata overrides legacy/planning fields only.
     for k,v in x.get('registry_metadata_adjudicated',{}).items():fields[k]=v
     for k,v in supplemental.get(t,({},None))[0].get('registry_metadata_adjudicated',{}).items():fields[k]=v
     country=(fields.get('domicile') or {}).get('value')
     countries={'Germany':'DE','Japan':'JP','United Kingdom':'GB','Netherlands':'NL','Switzerland':'CH','Canada':'CA','Australia':'AU','Taiwan':'TW','United States':'US'}
     if country in countries:
      fields['domicile']=dict(fields['domicile'],value=countries[country],source_country_label=country)
     blockers=[]
     for k in ['domicile','reporting_basis','sector']:
      field=fields.get(k,{})
      origin_row,origin_doc=m,{}
      if k in x.get('registry_metadata_adjudicated',{}): origin_row,origin_doc=x,(dom if ref.startswith('classification_domestic') else intl)
      if k in supplemental.get(t,({},None))[0].get('registry_metadata_adjudicated',{}): origin_row,origin_doc=supplemental[t][0],origins[t]
      if not valid_metadata(k,field,origin_row,origin_doc): blockers.append('invalid_or_unresolved_'+k)
     ident=m['identity_eligible'] is True and (m['basic_class_eligible'] is True or (t=='V' and eligible and x.get('tier_eligible') is True))
     row={'ticker':t,'proposed_size_tier':c['proposed_size_tier'],'reserved_holdout':c['reserved_holdout'],'issuer_deduplication_key':m['issuer_deduplication_key'],'classification_eligible':bool(eligible),'classification_evidence_ref':ref+'#'+t,'identity_class_eligible':bool(ident),'metadata_blockers':blockers,'metadata_fields':fields,'metadata_completion_ref':supplemental.get(t,({},None))[1],'company_admitted':bool(eligible and ident and not blockers),'admission_scope':'staged_metadata_admission_only_not_active_registry_or_quality_acceptance','exact_cap_verified_for_answers':False,'classification_limitations':x.get('limits',x.get('limitations',[])),'classification_exclusion_reason':x.get('blocked_reason') if not eligible else None}
     completion=supplemental.get(t,({},None))[0]
     row['metadata_source_context']={'completion_row_sources':completion.get('sources',[]),'completion_document_sources':origins.get(t,{}).get('sources',[]),'classification_row_sources':x.get('sources',[]),'classification_document_sources':(dom if ref.startswith('classification_domestic') else intl).get('sources',[]) if t in classified else []}
     row['metadata_dates']={k:v for k,v in completion.items() if k in {'document_period_end','document_publication_date','retrieved_at_utc','retrieved_on_utc'}}
     rows.append(row)
    admitted=[r for r in rows if r['company_admitted']];counts=Counter(r['proposed_size_tier']for r in admitted);classcounts=Counter(r['proposed_size_tier']for r in rows if r['classification_eligible'] and r['identity_class_eligible']);sectors={r['metadata_fields']['sector']['value']for r in admitted};tags={t for r in admitted for t in r['metadata_fields']['complexity_tags']['value']};tiers=['large','mid','small_micro']
    report={'schema_version':1,'updated_at':datetime.now(timezone.utc).isoformat(),'scope':'classification and field-level admission readiness; not an execution manifest','approval_ref':'approved_classification_only.json','summary':{'classification_eligible_count':sum(r['classification_eligible']for r in rows),'classification_and_identity_tier_counts':{t:classcounts[t]for t in tiers},'classification_excluded_tickers':[r['ticker']for r in rows if not r['classification_eligible']],'company_admitted_count':len(admitted),'admitted_tier_counts':{t:counts[t]for t in tiers},'issuer_shortfall':100-len(admitted),'minimum_tier_shortfalls':{t:max(0,30-counts[t])for t in tiers},'admitted_sector_count':len(sectors),'sector_shortfall':max(0,10-len(sectors)),'admitted_distinct_complexity_tags':len(tags),'tag_shortfall':max(0,20-len(tags)),'metadata_blocker_counts':dict(Counter(b for r in rows for b in r['metadata_blockers'])),'reserved_holdouts_admitted':sum(r['reserved_holdout']for r in admitted)},'registry_activation_allowed':len(admitted)==100 and all(counts[t]>=30 for t in tiers) and len(sectors)>=10 and len(tags)>=20,'execution_authorized':False,'holdout_membership_changed':False,'external_exposure':'unknown outside audited repositories; no new attestation','replacement_proposal_ref':'replacement_candidate_review.json','rows':rows}
    
    keys=[r['issuer_deduplication_key'] for r in rows]
    cohort_blockers=[]
    if len(rows)!=100: cohort_blockers.append('requires_100_candidates')
    if len(set(keys))!=100 or any(not isinstance(k,str) or not re.fullmatch(r'SEC_CIK:[0-9]{10}',k) for k in keys): cohort_blockers.append('requires_100_unique_CIKs')
    if {r['ticker'] for r in rows if r['reserved_holdout'] is True}!=HOLDOUTS or sum(r['reserved_holdout'] is True for r in rows)!=20 or set(plan.get('reserved_holdout',[]))!=HOLDOUTS or len(plan.get('reserved_holdout',[]))!=20: cohort_blockers.append('frozen_holdout_membership_changed')
    report['cohort_blockers']=cohort_blockers
    report['registry_activation_allowed']=report['registry_activation_allowed'] and not cohort_blockers
    report['holdout_membership_changed']='frozen_holdout_membership_changed' in cohort_blockers
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proposal_dir", type=Path)
    parser.add_argument("--output", type=Path, help="Write report to a new path; existing files are never overwritten")
    args = parser.parse_args()
    report = build_readiness(args.proposal_dir)
    if args.output:
        with args.output.open("x") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
    else:
        print(json.dumps({"summary": report["summary"], "cohort_blockers": report["cohort_blockers"], "registry_activation_allowed": report["registry_activation_allowed"]}, indent=2))

if __name__ == "__main__":
    main()
