/* Cookie sessions; project membership comes from the server, never a local role. */
window.CarrickAuth = (() => {
  let current, project, ready, started=false;
  const $ = selector => document.querySelector(selector);
  const safe = value => String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const remember=()=>{try{sessionStorage.setItem("carrick-session-context",JSON.stringify({current,project,savedAt:Date.now()}));}catch(_){/* Online access remains available when browser storage is restricted. */}};
  const savedContext=()=>{try{const value=JSON.parse(sessionStorage.getItem("carrick-session-context")||"null");return value?.current?.user?.id && Array.isArray(value.current.projects) ? value : null;}catch(_){return null;}};
  const headers=()=>current ? {"X-CSRF-Token":current.csrf,"X-Carrick-Project":project?.id||""} : {};
  async function api(path,body) {
    let response;
    try{response=await fetch(path,{method:body?"POST":"GET",signal:AbortSignal.timeout(15000),headers:{"Content-Type":"application/json",...headers()},...(body?{body:JSON.stringify(body)}:{})});}
    catch(failure){throw Object.assign(new Error(failure.name==="TimeoutError"?"Sign-in is taking longer than expected. Retry the connection.":"The server could not be reached. Retry the connection."),{transport:true});}
    let data;
    try{data=await response.json();}catch(_){throw new Error("The server returned an incomplete response. Retry the connection.");}
    if(!response.ok) throw new Error(data.error||"Request failed");
    return data;
  }
  function apply() {
    $("#auth-panel").hidden=true; $(".app-shell").hidden=false;
    document.body.dataset.role=project?.role||"none";
    $("#account-name").textContent=current.user.name;
    $("#account-role").textContent=project?.role||"No project selected";
    $("#project-select").innerHTML=current.projects.map(p=>`<option value="${safe(p.id)}">${safe(p.name)}</option>`).join("");
    if(project) $("#project-select").value=project.id;
    $("#member-form").hidden=project?.role!=="owner";
    $("#access-members").hidden=project?.role!=="owner";
    remember();
  }
  function showLogin(message="") {
    $(".app-shell").hidden=true; $("#auth-panel").hidden=false; $("#auth-message").textContent=message;
  }
  async function signedIn() {
    current=await api("/api/auth/me");
    project=current.projects.find(p=>p.id===project?.id)||current.projects[0];
    if(started){remember();location.reload();return;}
    apply(); if(ready) ready();
    started=true;
  }
  async function bootstrap() {
    $("#auth-retry").disabled=true;
    $("#auth-submit").disabled=true;
    $("#auth-message").textContent="Checking your session…";
    try {project=savedContext()?.project;await signedIn();}
    catch(error){
      try {
        const status=await api("/api/auth/status");
        $("#auth-form").dataset.setup=String(status.setup_required);
        $("#auth-name-field").hidden=!status.setup_required;
        $("#auth-name").required=status.setup_required;
        $("#auth-title").textContent=status.setup_required?"Set up your workspace":"Sign in to Carrick";
        $("#auth-submit").textContent=status.setup_required?"Create owner account":"Sign in";
        $("#auth-password").autocomplete=status.setup_required?"new-password":"current-password";
        $("#auth-submit").disabled=false;$("#auth-retry").hidden=true;showLogin();
      }catch(failure){
        const saved=savedContext();
        if(failure.transport && saved && Date.now()-saved.savedAt<12*3600000){current=saved.current;project=saved.project;apply();started=true;ready?.();}
        else {showLogin(failure.message);$("#auth-retry").hidden=false;}
      }
    }finally{$("#auth-retry").disabled=false;}
  }
  async function start() {
    $(".app-shell").hidden=true;
    $("#auth-submit").disabled=true;
    $("#auth-form").addEventListener("submit",async event=>{
      event.preventDefault(); const button=$("#auth-submit"); if(button.disabled)return; const label=button.textContent;button.disabled=true;button.textContent="Signing in…";$("#auth-form").setAttribute("aria-busy","true");$("#auth-message").textContent="";
      try {
        await api($("#auth-form").dataset.setup==="true"?"/api/auth/setup":"/api/auth/login",{name:$("#auth-name").value,email:$("#auth-email").value,password:$("#auth-password").value});
        $("#auth-password").value=""; await signedIn();
      } catch(error){ $("#auth-message").textContent=error.message; }
      finally {button.disabled=false;button.textContent=label;$("#auth-form").setAttribute("aria-busy","false");}
    });
    $("#auth-retry").addEventListener("click",bootstrap);
    $("#sign-out").addEventListener("click",async()=>{
      try {await api("/api/auth/logout",{});sessionStorage.removeItem("carrick-session-context");new BroadcastChannel("carrick-account").postMessage("logout");location.reload();}
      catch(error){window.alert(error.message);}
    });
    const channel=new BroadcastChannel("carrick-account");channel.onmessage=event=>{if(event.data==="logout"){sessionStorage.removeItem("carrick-session-context");location.reload();}};
    $("#project-select").addEventListener("change",()=>{project=current.projects.find(p=>p.id===$("#project-select").value);remember();location.reload();});
    $("#access-open").addEventListener("click",async()=>{
      $("#access-dialog").showModal();
      if(project?.role==="owner"){
        try {const members=await api("/api/members");$("#access-members").innerHTML=members.map(m=>`<p>${safe(m.name)} · ${safe(m.email)} · ${safe(m.role)}</p>`).join("");}
        catch(error){$("#access-message").textContent=error.message;}
      }
    });
    $("#access-close").addEventListener("click",()=>$("#access-dialog").close());
    $("#project-form").addEventListener("submit",async event=>{
      event.preventDefault();
      try {project=await api("/api/projects",{name:$("#project-name").value});await signedIn();location.reload();}
      catch(error){$("#access-message").textContent=error.message;}
    });
    $("#member-form").addEventListener("submit",async event=>{
      event.preventDefault();
      try {await api("/api/members",{email:$("#member-email").value,name:$("#member-name").value,password:$("#member-password").value,role:$("#member-role").value});$("#member-password").value="";$("#access-message").textContent="Project access saved. Share initial credentials through your secure channel.";}
      catch(error){$("#access-message").textContent=error.message;}
    });
    $("#password-form").addEventListener("submit",async event=>{event.preventDefault();try{await api("/api/auth/password",{current_password:$("#current-password").value,new_password:$("#new-password").value});$("#current-password").value="";$("#new-password").value="";await signedIn();}catch(error){$("#access-message").textContent=error.message;}});
    return new Promise(resolve=>{
      ready=resolve;
      bootstrap().catch(error=>{showLogin(error.message);$("#auth-retry").hidden=false;});
    });
  }
  return {start,headers,get current(){return current;},get project(){return project;},showLogin};
})();
