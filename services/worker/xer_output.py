"""Constrained actual-progress patch preserving all other XER table records."""
import hashlib
from services.worker.engine import parse_schedule


def progress_output(source,filename,claims):
    activities,relationships,kind=parse_schedule(source,filename)
    by_id={a["external_id"]:a for a in activities}
    expected={key:dict(a) for key,a in by_id.items()}
    proposals=[]
    for claim in claims:
        task=by_id.get(claim["selected_activity"])
        if not task or claim["kind"] not in {"actual_start","actual_finish"} or claim["status"] not in {"approved","exported"}:
            raise ValueError("Schedule output accepts only approved actuals on imported TASK IDs")
        before=(task.get(claim["kind"]) or "")[:10]
        if before and before!=claim["event_date"]: raise ValueError("Schedule output would overwrite an existing actual")
        prior=(expected[task["external_id"]].get(claim["kind"]) or "")[:10]
        if prior and prior!=claim["event_date"]: raise ValueError("Approved actual claims disagree; resolve them before output")
        expected[task["external_id"]][claim["kind"]]=claim["event_date"]
        proposals.append({"event_id":claim["id"],"source_report":claim["report_id"],"task_id":task["source_key"],"task_code":task["external_id"],
                          "field":"act_start_date" if claim["kind"]=="actual_start" else "act_end_date","before":before,"after":claim["event_date"],
                          "date_precision":"day","approved_at":claim["decided_at"],"decision_note":claim["decision_reason"]})
    manifest={"schema":"carrick-p6-changeset-v1","source_sha256":hashlib.sha256(source.encode()).hexdigest(),"changes":proposals,
              "preserves_task_ids":True,"preserves_taskpred":True,"requires_p6_recalculation":True,"oracle_import_verified":False}
    if kind!="xer":
        manifest.update(round_trip_verified=False,validation="Validated approved change set against the imported CSV; native XER requires an XER source")
        return None,manifest
    if any(a.get("actual_finish") and not a.get("actual_start") for a in expected.values()):
        manifest.update(round_trip_verified=False,validation="Native output withheld: a completed activity lacks an actual start. The change set retains the finish-only evidence")
        return None,manifest
    table,fields=None,[]
    output=[];seen=set(); changed_ids={p["task_code"] for p in proposals}
    for line in source.splitlines(keepends=True):
        ending="\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        parts=line.rstrip("\r\n").split("\t")
        if parts[0]=="%T": table=parts[1];fields=[]
        elif parts[0]=="%F": fields=parts[1:]
        elif parts[0]=="%R" and table=="TASK":
            original=parts[1:]; row=dict(zip(fields,original)); code=row.get("task_code") or row.get("task_id")
            if code in changed_ids:
                if code in seen: raise ValueError("TASK code occurs more than once in output")
                seen.add(code)
                if not {"act_start_date","act_end_date","status_code"}.issubset(fields): raise ValueError("TASK actual/status columns are required for native output")
                target=expected[code];values=original+[""]*max(0,len(fields)-len(original))
                for event_kind,field in (("actual_start","act_start_date"),("actual_finish","act_end_date")):
                    value=target.get(event_kind) or ""
                    # Retain existing timestamps; new source evidence has day precision.
                    if value[:10]!=(row.get(field) or "")[:10]: values[fields.index(field)]=value[:10]+" 00:00"
                values[fields.index("status_code")]= "TK_Complete" if target.get("actual_finish") else "TK_Active" if target.get("actual_start") else row.get("status_code","")
                if target.get("actual_finish") and "remain_drtn_hr_cnt" in fields: values[fields.index("remain_drtn_hr_cnt")]="0"
                allowed={"act_start_date","act_end_date","status_code","remain_drtn_hr_cnt"}
                for index,field in enumerate(fields):
                    if field not in allowed and values[index]!=(original[index] if index<len(original) else ""):
                        raise ValueError("Output changed a field outside the progress boundary")
                line="\t".join(["%R",*values])+ending
        output.append(line)
    if seen!=changed_ids: raise ValueError("An approved TASK was not found in native output")
    content="".join(output)
    imported,new_relationships,_=parse_schedule(content,filename)
    if relationships!=new_relationships or len(imported)!=len(activities): raise ValueError("Round-trip changed schedule structure")
    for task in imported:
        prior=by_id[task["external_id"]]; target=expected[task["external_id"]]
        if task["source_key"]!=prior["source_key"]: raise ValueError("Round-trip changed TASK identity")
        for field in ("actual_start","actual_finish"):
            if (task.get(field) or "")[:10]!=(target.get(field) or "")[:10]: raise ValueError("Round-trip actual does not match its approved proposal")
        for field in ("planned_start","planned_finish","name","wbs","location"):
            if task[field]!=prior[field]: raise ValueError("Round-trip changed baseline fields")
    manifest.update(round_trip_verified=True,output_sha256=hashlib.sha256(content.encode()).hexdigest(),validation="Constrained field diff and Carrick parser round-trip passed",timestamp_serialization="New day-precision dates serialize at 00:00; planners must confirm time semantics in P6")
    return content,manifest
