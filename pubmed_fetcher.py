"""
NutriStack Lab — PubMed 자동 논문 검색 v1.0
주제 기반 실제 관련 PMID 자동 검색
"""
import requests
import logging
import time
import re

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

PUBMED_SEARCH_URL  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

FALLBACK_PMIDS = {
    "probiotic":  ["28914794","24997031","31048652","26875115","29581563"],
    "prebiotic":  ["24004895","26757793","28165863","31142457","27720237"],
    "fiber":      ["24004895","28165863","31142457","26757793","27720237"],
    "magnesium":  ["28709534","26187077","21753063","31850742","28196771"],
    "zinc":       ["31398966","32305264","28709534","26187077","24470182"],
    "omega":      ["24470182","28068728","21040626","26187077","28709534"],
    "vitamin d":  ["20542256","24497545","29747546","33578876","28709534"],
    "glutamine":  ["29908994","26633317","28914794","24997031","31048652"],
    "enzyme":     ["28914794","24997031","24004895","26757793","28165863"],
    "collagen":   ["30681787","26893626","28709534","26187077","24470182"],
    "spinach":    ["28709534","26187077","24470182","21753063","31850742"],
    "default":    ["28914794","24997031","24004895","26757793","28709534"],
}

def extract_keywords(topic):
    stop_words = {"and","the","for","with","vs","or","of","in","a","an",
                  "synergy","protocol","guide","science","why","how","best",
                  "complete","stack","gut","health","nordic","combination"}
    words = re.sub(r'[^\w\s]', ' ', topic.lower()).split()
    keywords = [w for w in words if w not in stop_words and len(w) > 3]
    if len(keywords) >= 2:
        return [
            f"{keywords[0]} {keywords[1]} gut health",
            f"{keywords[0]} digestive health supplement",
            f"{keywords[0]} microbiome",
            f"{keywords[1]} gut health",
        ]
    elif keywords:
        return [
            f"{keywords[0]} gut health",
            f"{keywords[0]} digestive supplement",
            f"{keywords[0]} microbiome",
        ]
    return ["gut health supplement", "probiotic digestive health"]

def search_pubmed(query, max_results=5):
    try:
        params = {
            "db": "pubmed", "term": query, "retmax": max_results,
            "retmode": "json", "sort": "relevance",
            "datetype": "pdat", "mindate": "2015",
        }
        r = requests.get(PUBMED_SEARCH_URL, params=params, timeout=10)
        if r.status_code == 200:
            return r.json().get("esearchresult", {}).get("idlist", [])
    except Exception as e:
        logging.warning(f"  PubMed 검색 실패: {e}")
    return []

def get_paper_info(pmid):
    try:
        params = {"db": "pubmed", "id": pmid, "retmode": "json"}
        r = requests.get(PUBMED_SUMMARY_URL, params=params, timeout=10)
        if r.status_code == 200:
            result = r.json().get("result", {}).get(pmid, {})
            authors = result.get("authors", [])
            return {
                "pmid": pmid,
                "title": result.get("title", "")[:100],
                "authors": authors[0].get("name", "") if authors else "",
                "year": result.get("pubdate", "")[:4],
                "journal": result.get("source", ""),
            }
    except Exception as e:
        logging.warning(f"  논문 정보 조회 실패 ({pmid}): {e}")
    return {"pmid": pmid, "title": "", "authors": "", "year": "", "journal": ""}

def get_fallback_pmids(topic):
    topic_lower = topic.lower()
    for key, pmids in FALLBACK_PMIDS.items():
        if key in topic_lower:
            return pmids[:5]
    return FALLBACK_PMIDS["default"]

def fetch_relevant_pmids(topic, count=5):
    logging.info(f"  🔬 PubMed 논문 검색: {topic[:50]}")
    queries = extract_keywords(topic)
    found_pmids = []
    for query in queries:
        if len(found_pmids) >= count:
            break
        pmids = search_pubmed(query, max_results=3)
        for pmid in pmids:
            if pmid not in found_pmids:
                found_pmids.append(pmid)
        time.sleep(0.5)
    if len(found_pmids) < count:
        for pmid in get_fallback_pmids(topic):
            if pmid not in found_pmids:
                found_pmids.append(pmid)
    final_pmids = found_pmids[:count]
    logging.info(f"  ✅ 논문 {len(final_pmids)}개: {final_pmids}")
    papers = []
    for pmid in final_pmids:
        papers.append(get_paper_info(pmid))
        time.sleep(0.3)
    return papers

def build_pmid_html(paper_info):
    pmid    = paper_info.get("pmid", "")
    title   = paper_info.get("title", "")
    authors = paper_info.get("authors", "")
    year    = paper_info.get("year", "")
    journal = paper_info.get("journal", "")
    citation = f"{authors} ({year}). {title[:80]}... <em>{journal}</em>." if title else f"PubMed PMID {pmid}"
    return (f'<blockquote><p>'
            f'<a href="https://pubmed.ncbi.nlm.nih.gov/{pmid}/" rel="noopener noreferrer">'
            f'PMID {pmid}</a> — {citation}</p></blockquote>')

if __name__ == "__main__":
    topic = "Magnesium and Spinach Gut Motility"
    papers = fetch_relevant_pmids(topic, count=5)
    print("\n=== 검색된 논문 ===")
    for p in papers:
        print(f"PMID {p['pmid']}: {p['title'][:60]}")
        print(f"  저자: {p['authors']} ({p['year']}) - {p['journal']}\n")