var ROSE_MAIN_ID = "yaoVL8AlJ1oRMDq4dG";
var ROSE_ACT_ID = "3mpyYVMLl7odM9Wax5";

//Rose ID
var reportID = getActName() ? ROSE_ACT_ID : ROSE_MAIN_ID;
console.log(reportID, getActName());
var aegis = new Aegis({
    id: reportID,
    reportApiSpeed: true,
    reportAssetSpeed: true,
    spa: true
}); 

// get uin from cookie
var uin = chGetCookie("uin");
if (uin && uin.length > 0) {
    uin = uin.match(/\d+/);
    uin = parseInt(uin[0], 10);
}
else {
    uin = 0;
}
if (uin) {
    aegis.setConfig({
        "uin": uin
    })
}
aegis.time('s1.domReady');

function chGetCookie(key){
    var _cookie = document.cookie;
    var items = _cookie.split("; ");
    var item = [];
    var size = items.length;
    for (var i = 0; i < size; i++) {
        item = items[i].split("=");
        if (key == item[0] && item.length == 2) {
            return item[1];
        }
    }
    return "";
}

$(document).ready(function () {
    aegis.timeEnd('s1.domReady');
    
    //BuriedPoint(Not ACT)
    if(!getActName()){
        aegis.time('s2.frameworkReady');
        //Open the domain name start burying point
        var v = !!(window.external && window.external["callHallApi"]); 
        var buried_type = v ? 5 : 2;
        
        var systemParam = "";
        var browserParam = "";
		if (window["roseUAParser"]) {
			var OSInfo = window["roseUAParser"].getOS();
			var browserInfo = window["roseUAParser"].getBrowser();

			systemParam = OSInfo && (OSInfo.name + OSInfo.version) || "";
			browserParam = browserInfo && (browserInfo.name + browserInfo.major) || "";
		}
		
        jQuery.ajax({
            type: "post",
            url: "http://localhost:8088/cgi-bin/rosary_buried_point?gprand=" + Math.random() * Math.random(),
            data: {type: buried_type, param: 1, system: systemParam, browser: browserParam},
            xhrFields: {
                withCredentials: true //Cookie
            },
            success: (res) => {
                console.log("start load h5:",res);
            },
            error: (err) => {
                console.log("start load h5:",err);
            }
        });
    }
    else{
        console.log("Buried points are not counted for activities s1");
    }

})