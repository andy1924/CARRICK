/* Cookie sessions; project membership comes from the server, never a local role. */
window.CarrickAuth = (() => {
  let current, project, ready, started=false;
  const $ = selector => document.querySelector(selector);
  const safe = value => String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const remember=()=>sessionStorage.setItem("carrick-session-context",JSON.stringify({current,project,savedAt:Date.now()}));
  const headers=()=>current ? {"X-CSRF-Token":current.csrf,"X-Carrick-Project":project?.id||""} : {};
  async function api(path,body) {
    const response=await fetch(path,{method:body?"POST":"GET",headers:{"Content-Type":"application/json",...headers()},...(body?{body:JSON.stringify(body)}:{})});
    const data=await response.json();
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
  async function start() {
    $(".app-shell").hidden=true;
    $("#auth-submit").disabled=true;
    $("#auth-form").addEventListener("submit",async event=>{
      event.preventDefault(); const button=$("#auth-submit"); button.disabled=true;
      try {
        await api($("#auth-form").dataset.setup==="true"?"/api/auth/setup":"/api/auth/login",{name:$("#auth-name").value,email:$("#auth-email").value,password:$("#auth-password").value});
        $("#auth-password").value=""; await signedIn();
      } catch(error){ $("#auth-message").textContent=error.message; }
      finally {button.disabled=false;}
    });
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
    return new Promise(async resolve=>{
      ready=resolve;
      try {const saved=JSON.parse(sessionStorage.getItem("carrick-session-context")||"null");project=saved?.project;await signedIn();}
      catch(error){
        try {const status=await api("/api/auth/status");$("#auth-form").dataset.setup=String(status.setup_required);$("#auth-name-field").hidden=!status.setup_required;$("#auth-title").textContent=status.setup_required?"Set up your workspace":"Sign in to Carrick";$("#auth-submit").textContent=status.setup_required?"Create owner account":"Sign in";$("#auth-submit").disabled=false;showLogin();}
        catch(_){const saved=JSON.parse(sessionStorage.getItem("carrick-session-context")||"null");if(saved?.current&&Date.now()-saved.savedAt<12*3600000){current=saved.current;project=saved.project;apply();started=true;resolve();}else showLogin("Connect to the local server to sign in.");}
      }
    });
  }
  return {start,headers,get current(){return current;},get project(){return project;},showLogin};
})();
