
var allData=[], filteredData=[], currentPage=1, pageSize=30, cookieName='ip_detect_admin';
var adminMap=null, mapMarkers=[], trendChart=null, countryChart=null, ispChart=null, refreshTimer=null;
var pendingDeleteIndex = -1;

function getCookie(n){var m=document.cookie.match(new RegExp('(^| )'+n+'=([^;]+)'));return m?m[2]:'';}
function setCookie(n,v){document.cookie=n+'='+v+'; path=/; max-age=86400';}
function delCookie(n){document.cookie=n+'=; path=/; max-age=0';}
(function(){var t=getCookie(cookieName);if(t)showAdmin();})();

function doLogin(){
    var pwd=document.getElementById('pwdInput').value.trim();
    if(!pwd){document.getElementById('loginError').style.display='block';return;}
    var btn=document.querySelector('.login-box button');
    btn.disabled=true;btn.textContent='...';
    fetch('/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pwd})})
    .then(function(r){if(r.ok)return r.json();return r.text().then(function(t){throw new Error(t);});})
    .then(function(d){setCookie(cookieName,d.token);showAdmin();btn.disabled=false;btn.textContent='Login';})
    .catch(function(e){document.getElementById('loginError').style.display='block';btn.disabled=false;btn.textContent='Login';setTimeout(function(){document.getElementById('loginError').style.display='none';},5000);});}
function doLogout(){delCookie(cookieName);document.getElementById('adminPanel').style.display='none';document.getElementById('loginPage').style.display='flex';if(refreshTimer)clearInterval(refreshTimer);}

function showAdmin(){document.getElementById('loginPage').style.display='none';document.getElementById('adminPanel').style.display='block';initMap();loadData();if(refreshTimer)clearInterval(refreshTimer);refreshTimer=setInterval(loadData,30000);}

function initMap(){if(adminMap)return;adminMap=L.map('adminMap',{zoomControl:true}).setView([30,110],2);L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{attribution:'漏OSM 漏CARTO',maxZoom:18}).addTo(adminMap);}

function loadData(){
    var token=getCookie(cookieName);
    fetch('/api/admin/visits',{headers:{'Authorization':'Bearer '+token}})
    .then(function(r){if(r.status===401){doLogout();return null;}return r.json();})
    .then(function(d){if(!d)return;allData=d.visits||[];allData.reverse();buildFilters();filterData();updateStats();updateMap();updateCharts();});
}

function updateStats(){
    document.getElementById('sTotal').textContent=allData.length;
    var today=new Date().toISOString().slice(0,10);
    var todayCount=allData.filter(function(v){return v.time&&v.time.startsWith(today)}).length;
    document.getElementById('sToday').textContent=todayCount;
    var ips={},countries={},isps={},now=Date.now(),recent1h=0;
    allData.forEach(function(v){ips[v.ip]=(ips[v.ip]||0)+1;if(v.country_code)countries[v.country_code]=1;if(v.isp&&v.isp!=='鏈煡')isps[v.isp]=(isps[v.isp]||0)+1;if(v.time){var t=new Date(v.time.replace(/-/g,'/')).getTime();if(now-t<3600000)recent1h++;}});
    document.getElementById('sUnique').textContent=Object.keys(ips).length;
    document.getElementById('sCountries').textContent=Object.keys(countries).length;
    document.getElementById('sRecent').textContent=recent1h;
    var topISP=Object.entries(isps).sort(function(a,b){return b[1]-a[1]})[0];
    document.getElementById('sTopISP').textContent=topISP?(topISP[0].length>12?topISP[0].substring(0,11)+'..':topISP[0]):'-';
}

function buildFilters(){
    var cs={},isps={};
    allData.forEach(function(v){if(v.country)cs[v.country]=v.country_code||'';if(v.isp&&v.isp!=='鏈煡')isps[v.isp]=1;});
    var cSel=document.getElementById('countryFilter');cSel.innerHTML='<option value="">鍏ㄩ儴鍥藉</option>';
    Object.keys(cs).sort().forEach(function(c){var o=document.createElement('option');o.value=cs[c];o.textContent=c;cSel.appendChild(o);});
    var iSel=document.getElementById('ispFilter');iSel.innerHTML='<option value="">鍏ㄩ儴ISP</option>';
    Object.keys(isps).sort().forEach(function(i){var o=document.createElement('option');o.value=i;o.textContent=i;iSel.appendChild(o);});
}

function codeToFlag(code){if(!code||code.length!==2)return '馃弫';var offset=127397;return String.fromCodePoint(code.charCodeAt(0)+offset)+String.fromCodePoint(code.charCodeAt(1)+offset);}

function filterData(){
    var q=document.getElementById('searchInput').value.toLowerCase();
    var cc=document.getElementById('countryFilter').value;
    var isp=document.getElementById('ispFilter').value;
    filteredData=allData.filter(function(v){
        var matchQ=!q||(v.ip&&v.ip.toLowerCase().indexOf(q)>-1)||(v.city&&v.city.toLowerCase().indexOf(q)>-1)||(v.isp&&v.isp.toLowerCase().indexOf(q)>-1)||(v.country&&v.country.toLowerCase().indexOf(q)>-1);
        return matchQ&&(!cc||v.country_code===cc)&&(!isp||v.isp===isp);
    });
    currentPage=1;renderTable();
}

function renderTable(){
    var tbody=document.getElementById('tableBody');
    var total=filteredData.length;
    var totalPages=Math.ceil(total/pageSize)||1;
    if(currentPage>totalPages)currentPage=totalPages;
    var start=(currentPage-1)*pageSize;
    var end=Math.min(start+pageSize,total);
    var pageData=filteredData.slice(start,end);
    if(pageData.length===0){tbody.innerHTML='<tr><td colspan="9"><div class="empty"><div class="emoji">馃摥</div>鏆傛棤璁板綍</div></td></tr>';}
    else{
        var html='';
        pageData.forEach(function(v,i){
            var idx=start+i+1;
            var ua=v.user_agent||'-';
            var shortUa=ua.length>35?(ua.indexOf('Chrome')>-1&&ua.indexOf('Edg')>-1?'Edge':ua.indexOf('Chrome')>-1?'Chrome':ua.indexOf('Firefox')>-1?'Firefox':ua.indexOf('Safari')>-1?'Safari':ua.substring(0,32)+'..'):ua;
            html+='<tr>';
            html+='<td>'+idx+'</td>';
            html+='<td class="ip-cell" onclick="showDetail(\''+v.ip+'\')">'+v.ip+'</td>';
            html+='<td class="flag-cell">'+codeToFlag(v.country_code)+'</td>';
            html+='<td>'+(v.country||'-')+'</td>';
            html+='<td>'+(v.city||'-')+(v.region&&v.region!=='鏈煡'?'<br><span style="font-size:10px;color:var(--text-muted)">'+v.region+'</span>':'')+'</td>';
            html+='<td style="font-size:11px">'+(v.isp||'-')+'</td>';
            html+='<td class="ua-cell" title="'+ua.replace(/"/g,'&quot;')+'">'+shortUa+'</td>';
            html+='<td class="time-cell">'+(v.time||'-')+'</td>';
            html+='<td><a class="map-link" href="https://www.google.com/maps?q='+(v.latitude||0)+','+(v.longitude||0)+'" target="_blank">馃搷</a> <span class="detail-link" onclick="showDetail(\''+v.ip+'\')">璇︽儏</span><span class="del-link" onclick="showDelConfirm('+i+')">鉁?/span></td>';
            html+='</tr>';
        });
        tbody.innerHTML=html;
    }
    var pagDiv=document.getElementById('pagination');
    if(totalPages<=1){pagDiv.innerHTML='<span>鍏?'+total+' 鏉?/span>';return;}
    var phtml='<button onclick="goPage('+(currentPage-1)+')" '+(currentPage===1?'disabled':'')+'>涓婁竴椤?/button>';
    var startP=Math.max(1,currentPage-4),endP=Math.min(totalPages,currentPage+4);
    for(var p=startP;p<=endP;p++)phtml+='<button class="'+(p===currentPage?'active':'')+'" onclick="goPage('+p+')">'+p+'</button>';
    phtml+='<button onclick="goPage('+(currentPage+1)+')" '+(currentPage===totalPages?'disabled':'')+'>涓嬩竴椤?/button>';
    phtml+='<span style="margin-left:10px">'+total+'鏉?/ '+totalPages+'椤?/span>';
    pagDiv.innerHTML=phtml;
}

function goPage(p){var totalPages=Math.ceil(filteredData.length/pageSize)||1;if(p<1||p>totalPages)return;currentPage=p;renderTable();}

function showDetail(ip){
    var v=allData.find(function(x){return x.ip===ip;});
    if(!v){alert('鏈壘鍒拌褰?);return;}
    document.getElementById('detailTitle').textContent='馃實 '+ip+' 璇︽儏';
    var html='',fields=[['IP鍦板潃',v.ip],['鍥藉',(v.country||'-')+' '+codeToFlag(v.country_code)],['鍩庡競',v.city||'-'],['鍦板尯',v.region||'-'],['缁忕含搴?,(v.latitude||'')+', '+(v.longitude||'')],['鏃跺尯',v.timezone||'-'],['ISP',v.isp||'-'],['AS缂栧彿',v.as||'-'],['閭紪',v.zip||'-'],['璁块棶鏃堕棿',v.time||'-']];
    fields.forEach(function(f){html+='<div class="modal-row"><div class="label">'+f[0]+'</div><div class="value">'+f[1]+'</div></div>';});
    document.getElementById('detailInfo').innerHTML=html;
    var lat=v.latitude||0,lon=v.longitude||0;
    var mapUrl='https://www.openstreetmap.org/export/embed.html?bbox='+(lon-0.05)+','+(lat-0.05)+','+(lon+0.05)+','+(lat+0.05)+'&layer=mapnik&marker='+lat+','+lon;
    document.getElementById('detailMap').innerHTML='<iframe src="'+mapUrl+'" loading="lazy"></iframe>';
    document.getElementById('detailModal').style.display='flex';
}
function closeDetail(){document.getElementById('detailModal').style.display='none';}

function showDelConfirm(idx){pendingDeleteIndex=idx;var v=filteredData[idx];document.getElementById('delConfirmText').textContent='纭鍒犻櫎 '+v.ip+' 鐨勮褰曪紵';document.getElementById('delConfirmModal').style.display='flex';}
function closeDelConfirm(){document.getElementById('delConfirmModal').style.display='none';pendingDeleteIndex=-1;}
function doDelete(){
    if(pendingDeleteIndex<0)return;
    var v=filteredData[pendingDeleteIndex];
    var token=getCookie(cookieName);
    fetch('/api/admin/visits/'+encodeURIComponent(v.ip),{method:'DELETE',headers:{'Authorization':'Bearer '+token}})
    .then(function(r){if(r.status===401){doLogout();return;}closeDelConfirm();loadData();});
}

function updateMap(){
    if(!adminMap)return;mapMarkers.forEach(function(m){adminMap.removeLayer(m);});mapMarkers=[];
    var seen={};allData.forEach(function(v){if(seen[v.ip])return;seen[v.ip]=1;var lat=parseFloat(v.latitude),lon=parseFloat(v.longitude);if(isNaN(lat)||isNaN(lon))return;var flag=codeToFlag(v.country_code);var popup='<b>'+flag+' '+(v.city||'鏈煡')+'</b><br>IP: '+v.ip+'<br>ISP: '+(v.isp||'鏈煡')+'<br>'+(v.time||'');var marker=L.circleMarker([lat,lon],{radius:5,fillColor:'#7c4dff',color:'#448aff',weight:1,opacity:0.8,fillOpacity:0.6}).addTo(adminMap).bindPopup(popup);mapMarkers.push(marker);});
    if(mapMarkers.length>0)adminMap.fitBounds(mapMarkers.map(function(m){return m.getLatLng()}),{padding:[30,30],maxZoom:6});
}

function updateCharts(){
    var days={};for(var i=6;i>=0;i--){var d=new Date(Date.now()-i*86400000);days[d.toISOString().slice(0,10)]=0;}
    allData.forEach(function(v){if(v.time){var d=v.time.substring(0,10);if(d in days)days[d]++;}});
    var labels=Object.keys(days).map(function(d){return d.substring(5);}),values=Object.values(days);
    var ctx1=document.getElementById('trendChart').getContext('2d');
    if(trendChart)trendChart.destroy();
    trendChart=new Chart(ctx1,{type:'line',data:{labels:labels,datasets:[{label:'璁块棶閲?,data:values,borderColor:'#7c4dff',backgroundColor:'rgba(124,77,255,0.1)',fill:true,tension:0.4,pointBackgroundColor:'#18ffff',pointRadius:4}]},options:{responsive:true,plugins:{legend:{display:false}},scales:{x:{ticks:{color:'#5c6bc0'},grid:{color:'rgba(124,77,255,0.08)'}},y:{ticks:{color:'#5c6bc0',stepSize:1},grid:{color:'rgba(124,77,255,0.08)'},beginAtZero:true}}}});
    var ccs={};allData.forEach(function(v){if(v.country&&v.country!=='鏈煡')ccs[v.country]=(ccs[v.country]||0)+1;});
    var cSorted=Object.entries(ccs).sort(function(a,b){return b[1]-a[1]}).slice(0,5);
    var ctx2=document.getElementById('countryChart').getContext('2d');
    if(countryChart)countryChart.destroy();
    countryChart=new Chart(ctx2,{type:'doughnut',data:{labels:cSorted.map(function(x){return x[0]}),datasets:[{data:cSorted.map(function(x){return x[1]}),backgroundColor:['#7c4dff','#448aff','#18ffff','#69f0ae','#ffd740'],borderColor:'#111640',borderWidth:2}]},options:{responsive:true,plugins:{legend:{position:'bottom',labels:{color:'#9fa8da',font:{size:11}}}}}});
    var isps={};allData.forEach(function(v){if(v.isp&&v.isp!=='鏈煡')isps[v.isp]=(isps[v.isp]||0)+1;});
    var iSorted=Object.entries(isps).sort(function(a,b){return b[1]-a[1]}).slice(0,5);
    var ctx3=document.getElementById('ispChart').getContext('2d');
    if(ispChart)ispChart.destroy();
    ispChart=new Chart(ctx3,{type:'doughnut',data:{labels:iSorted.map(function(x){return x[0].length>18?x[0].substring(0,16)+'..':x[0]}),datasets:[{data:iSorted.map(function(x){return x[1]}),backgroundColor:['#ff5252','#ff9100','#ffd740','#69f0ae','#18ffff'],borderColor:'#111640',borderWidth:2}]},options:{responsive:true,plugins:{legend:{position:'bottom',labels:{color:'#9fa8da',font:{size:11}}}}}});
}

function exportCSV(){
    var token=getCookie(cookieName);
    fetch('/api/admin/visits',{headers:{'Authorization':'Bearer '+token}})
    .then(function(r){return r.json();}).then(function(d){
        var visits=d.visits||[];if(!visits.length){alert('鏃犺褰?);return;}
        var csv='锘縄P,鍥藉,鍥藉浠ｇ爜,鍩庡競,鍦板尯,绾害,缁忓害,鏃跺尯,ISP,AS,UA,鏉ユ簮,鏃堕棿
';
        visits.forEach(function(v){csv+=[v.ip,v.country,v.country_code,v.city,v.region,v.latitude,v.longitude,v.timezone,v.isp,v.as||'','"'+(v.user_agent||'').replace(/"/g,'""')+'"',v.referer||'',v.time].join(',')+'
';});
        var blob=new Blob([csv],{type:'text/csv;charset=utf-8'});var url=URL.createObjectURL(blob);var a=document.createElement('a');a.href=url;a.download='ip_visits_'+new Date().toISOString().slice(0,10)+'.csv';a.click();URL.revokeObjectURL(url);
    });
}
function showConfirm(){document.getElementById('confirmModal').style.display='flex';}
function closeConfirm(){document.getElementById('confirmModal').style.display='none';}
function doClear(){var token=getCookie(cookieName);fetch('/api/admin/clear',{method:'POST',headers:{'Authorization':'Bearer '+token}}).then(function(r){if(r.status===401){doLogout();return;}closeConfirm();loadData();});}

