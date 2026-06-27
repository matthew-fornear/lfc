var openedWindow = null;
var pleaseWaitDlg = null;
const XTYPE_ERROR = "error";
const XTYPE_WARNING = "warning";
const XTYPE_INFO = "info";
window.onpageshow = function (ev) {
    loadingHandler.navigateComplete();
}
function testCookies() {
    if (typeof(skipCookieTest) != "undefined" && skipCookieTest)
        return undefined;
    var r = navigator.cookieEnabled;
    if (typeof r == "undefined")
        r = $.cookies.test();
    return r;
}

function createNavForm(params) {
    var form = document.getElementById("_formNav");
    if (!form) {
        form = document.createElement("form");
        form.id = "_formNav";
        form.method = "POST";
        document.body.appendChild(form);
    } else {
        form.innerHTML = "";
        form.target = "_self";
        form.action = "";
    }
    for (paramName in params) {
        if (typeof (params[paramName]) != "undefined") {
            var input = document.createElement("input");
            input.name = paramName;
            input.value = params[paramName];
            input.type = "hidden";
            form.appendChild(input);
        }
    }
    return form;
}

function open_url(url) {
    if (url === '')
        return;
    var arrURL = url.split('?');
    if (arrURL.length > 1) {
        var param, params=new Object();
        var arrParams = arrURL[1].split("&");
        for (var i = 0; i < arrParams.length; i++) {
            param = arrParams[i].split("=");
            if (param.length > 2)
                params[param[0]] = param.splice(1).join("=");
            else if (param.length > 1)
                params[param[0]] = param[1];
            else
                params[param[0]] = "";
        }
        openPage(arrURL[0], params);
    } else {
        openPage(arrURL[0]);
    }
}

function open_page(strParams, strTarget)/*This function is depricated. Use openPage instead*/
{

    var params;
    if (strParams !== '') {
        var paramPair, paramPairs;
        params = new Object();
        paramPairs = strParams.split('|**|');
        for (var i = 0; i < paramPairs.length; i++) {
            paramPair = paramPairs[i].split('=');
            params[paramPair[0]] = paramPair[1];
        }
    }
    openPage(strTarget, params);
}

function openPage(query, postParams, target) {
    if (typeof (postParams) == "undefined") {
        window.location.assign(query);
    } else {
        var form = createNavForm(postParams);
        form.action = query;
        if (typeof (target) != "undefined") form.target = target;
        form.submit();
    }
}

// Getting the formatted currency string value
// input=string/number output=formatted string 
function my_format_currency(num, flag) {
    var my_number = 0.0, strNumber, i;
    var decimal_places = $eSRO.decimalPlaces;
    my_number = parseFloat(num);
    strNumber = my_number.toString(10);

    if (strNumber.indexOf('.') > 0) {
        var mPlace, mLen, mCount;
        mPlace = strNumber.indexOf('.');
        mLen = strNumber.length;
        mCount = mLen - mPlace - 1;
        if (mCount < decimal_places) {
            for (i = mCount; i < decimal_places; i++)
                strNumber += '0';
        } else if (mCount > decimal_places) {
            if (typeof (flag) == 'undefined') {
                strNumber = round(num).toString(10);
                strNumber = my_format_currency(strNumber, true);
            } else {
                strNumber = strNumber.substring(0, strNumber.indexOf('.') + decimal_places);
            }
        }
        strNumber = strNumber.replace('.', $eSRO.decimalSeparator);
    }
    else {
        if (decimal_places > 0) {
            strNumber += $eSRO.decimalSeparator;
            for (i = 0; i < decimal_places; i++)
                strNumber += '0';
        }
    }

    return strNumber;

}

function FormatCurrency(sum, symbol, noControlChars, decimalSeparator) {
    if (isNaN(sum) && sum.constructor == String) {
       sum = parseFloatX(sum);
    }
    if (!symbol && noControlChars==undefined) {
        noControlChars = true;
    }
    if (isNaN(sum))
        throw sum + ' is NaN';
    num = round(sum);
    var isNegative = num < 0;
    num = Math.abs(num);
    var fixed = Math.floor(num);
    var remainder = "";
    if (num > fixed) {
        remainder= new String(num);
        remainder = remainder.substr((new String(fixed)).length + 1, $eSRO.decimalPlaces);
    }
    while (remainder.length < $eSRO.decimalPlaces)
        remainder += '0';

    var pattern = sum >= 0 ? $eSRO.positiveCurrencyPattern : $eSRO.negativeCurrencyPattern;
    if (noControlChars) {
        pattern = pattern.replace(/\u202A|\u202C/g, "");
    }
    return pattern.format(
            fixed + (decimalSeparator!=undefined? decimalSeparator : $eSRO.decimalSeparator) + remainder,
            symbol!=undefined ?  symbol : $eSRO.defaultCurrencySign
        ).trim();
}

//eXtended function for parsing float numbers from strings with comma as a decimal separator
function getGroupSeparatorForRegExp() {
    if ($eSRO.thousandsSeparator == ".") {
        return "\\.";
    }
    if ($eSRO.thousandsSeparator.charCodeAt(0) == 160) {
        return "\\s";
    }
    return $eSRO.thousandsSeparator;
}
function removeThousandsSeparators(str) {
    if (str.length <= 4)
        return str;
    return str.replace(new RegExp(getGroupSeparatorForRegExp(), "g"), '');
}
function parseFloatX(str) {
    return parseFloat(
        removeThousandsSeparators(str.toString()).
        replace(/\u202A|\u202C/g,"").
        replace($eSRO.decimalSeparator, '.')
    );
}
function parseLocalNum(num) {
    var numWithoutGroupSep = removeThousandsSeparators(num.toString());
    
    var regExp = new RegExp("^([0-9]{0,10}(" + getGroupSeparatorForRegExp() + "[0-9]{3})*(" + $eSRO.decimalSeparator + "[0-9]{1,2})?)$");
    var match = numWithoutGroupSep.match(regExp);
    if (match == null)
        return isNaN;

    return parseFloat(num.replace($eSRO.decimalSeparator, '.'));
}
function getNumberInBrowserLocalFormat(num) {
    return +(num.replace((1.5).toLocaleString().substr(1, 1), "."));
}
function round(num) {
    var dec = Math.pow(10, $eSRO.decimalPlaces);
    return Math.round(num * dec) / dec;
}

function open_popup(strParams, strTarget, mTop, mLeft, mWidth, mHeight) {
    var params, frmPP;

    if (strTarget === '')
        return;

    if (openedWindow !== null) {
        try {
            openedWindow.close();
        }
        catch (e) {
            openedWindow = null;
        }
    }

    params = "top=" + mTop + ",left=" + mLeft + ",height=" + mHeight + ",width=" + mWidth + ",status=no,toolbar=no,menubar=no,location=no,center=1";
    var args=new Object();
    if (typeof (strParams) == "string") {
        arrParams = strParams.split('|**|');
        var arg;
        for (var i = 0; i < arrParams.length; i++) {
            arg = arrParams[i].split("=");
            args[arg[0]] = arg[1];
        }
        if (strParams !== '')
            args['H'] = mHeight;
    } else {
        args = strParams;
    } 
    
    frmPP = createNavForm(args);
    frmPP.action = strTarget;
    
    try {
        if (window.parent.name == 'eSRO_Opened') {
            openedWindow = window.open('', 'eSRO_Opened_1', params);
            frmPP.target = 'eSRO_Opened_1';

        }
        else {
            openedWindow = window.open('', 'eSRO_Opened', params);
            frmPP.target = 'eSRO_Opened';
        }
    }
    catch (e) {
        openedWindow = window.open('', 'eSRO_Opened', params);
        frmPP.target = 'eSRO_Opened';
    }
    frmPP.submit();
}
function addEventHandler(target, handler, type, IEtype) {
    if (target.attachEvent) {
        if (typeof (IEtype) != 'undefined') type = IEtype;
        target.attachEvent(type, handler);
    } else if (target.addEventListener) {
        target.addEventListener(type, handler, false);
    } else
        return false;
    return true;
}

//event.srcElement is non-standard so it is not working in firefox etc.
function getEventTarget(event) {
    event = event || window.event;
    var target = event.target || event.srcElement;

    return target;
}


function makeXMLHttpObj() {
    var xmlHttp = null;
    if (window.XMLHttpRequest) { // If IE7, Mozilla, Safari, and so on: Use native object 
        xmlHttp = new XMLHttpRequest();
    } else {
        if (window.ActiveXObject) { // ...otherwise, use the ActiveX control for IE5.x and IE6
            var ARR_ACTIVEX = ["MSXML2.XMLHttp.5.0",
                    "MSXML2.XMLHttp.4.0",
                    "MSXML2.XMLHttp.3.0",
                    "MSXML2.XMLHttp",
                    "Microsoft.XMLHttp"];
            var bFound = false;
            for (i = 0; i < ARR_ACTIVEX.length && !bFound; i++) {
                try {
                    xmlHttp = new ActiveXObject(ARR_ACTIVEX[i]);
                    bFound = true;
                }
                catch (e) {
                }
            }
        }
    }
    return xmlHttp;
}
//Depricated function, use string.trim instead!
function trimString(str) {
    return str.trim();
}

function invalidateField(fieldToInvalidate) //TODO: move to details_forms_functions
{
    if (fieldToInvalidate.type.toLowerCase() == "text") {
        fieldToInvalidate.style.backgroundColor = "#fdff73";
    }
}

function validateField(fieldToValidate) //TODO: move to details_forms_functions
{
    if (fieldToValidate.type.toLowerCase() == "text") {
        fieldToValidate.style.backgroundColor = "";
    }
}
function showPleaseWait(message) {  
    var dialogElement = $("<div class='plzWait'><div class='ajax-refreshing container' style='display:inline-block'></div><span class='msg'></span></div>");

    if (typeof (message) == 'undefined' || message==="") {
            message = gResources['plsWait'];
    }

    
    dialogElement.find('.msg').text(message);
    var options = {
        dialogClass: 'alert-dialog no-close',
        resizable: false,
        modal: true
    };
    if ($("body").is(".dir-RTL")) {
        $.extend(options, { position: { my: "center", at: "center", of: window, using: function(pos) {
            var me = $(this);
            me.css("right", pos.left)
                .css("top", pos.top);
            }
        }});
    }
    dialogElement.dialog(options);
    return dialogElement;
}

///
// show error message in a dialog box
// xtype - can be 'error' , 'warning' , 'info'.  default='error'
// decides which icon to show and which style to use
// arrayOfButtons is an array containing objects like {text,css,callback,default}. it will remove the OK button, and show the buttons in the array.
// A button with no callback will simply close the dialog.
// props - more dialog properties: {closeOnEscape:boolean default false}
///
function showPopupMessage(message, xtype, callback, arrayOfButtons, props) {

    if (message=='*')
        message = 'You have a new demo popup \non your \nscreen or whatever. To read your messages Cest fugitatur,\n sedissimus et id quas de cor ad moluptat.\nDus expedita ipitas que comnis es milibeatem.'

    if ((arrayOfButtons == null || $.isPlainObject(arrayOfButtons) && props == null) && $.isArray(callback)) {
        if ($.isPlainObject(arrayOfButtons) && props == null) {
            props = arrayOfButtons;
        }
        arrayOfButtons = callback;
        callback = null;
    }

    if (typeof (xtype) == 'function') {
        callback = xtype;
        xtype = null;
    }

    if (callback == null && arrayOfButtons == null && $.isArray(xtype)) {
        arrayOfButtons = xtype;
        xtype = null;
    }

    if (xtype == null) xtype = 'error';
    //&#xf057;&#xf071;&#xf05a
    var header = "<div class='showPopupMessage-header'><span class='showPopupMessage-errorheaderIcon'></span><span class='showPopupMessage-errorheader'>Error!</span></div>";
    if (xtype == 'warning' || xtype == 'warn')
        header = "<span class='showPopupMessage-warningheaderIcon'></span><span class='showPopupMessage-warningheader'>Warning</span>";
    if (xtype == 'information' || xtype == 'info')
        header = "<span class='showPopupMessage-infoheaderIcon'></span><span class='showPopupMessage-infoheader'>Information</span>";

    var classes = {
        "ui-dialog": "ui-corner-all alert-dialog no-close showPopupMessageContainer",
        "ui-dialog-titlebar": "showPopupMessage-titlebarheight",
        "ui-dialog-buttonpane": "showPopupMessage-buttonpane"
    }

    var buttonClass;

    if (xtype == 'error' || xtype == 'warning') {
        classes["ui-dialog"] += ' showPopupMessage-red';
        buttonClass = "ui-button showPopupMessage-redbutton";
    }
    else {
        classes["ui-dialog"] += ' showPopupMessage-blue';
        buttonClass = "ui-button showPopupMessage-bluebutton";
    }

    var dialogElement = $("<div class='showPopupMessage' role='alert' aria-live='assertive' aria-hidden='false' aria-atomic='true'>" +
        header +
        "<div class='showPopupMessage_msg'></div></div>");

    if (typeof (message) == 'undefined' || message === "") {
        message = 'Unknown Error';
    }

    var width = $(window).width()-60;
    if (width > 520)
        width = 520;

    var buttons = [];
    if (!arrayOfButtons) {
        buttons.push({
            'class': buttonClass,
            text: "OK",
            click: function () {
                $(this).dialog("close");
                if (callback) {
                    setTimeout(function () {
                        callback(false);
                    }, 0)
                }
            }
        });
    }
    else {
        function setButtons(i) {
            if (i < arrayOfButtons.length) {
                var btprops = arrayOfButtons[i];
                buttons.push({
                    'class': btprops.css ? "ui-button " + btprops.css : buttonClass,
                    text: btprops.text,
                    autofocus: !!btprops.default,
                    click: function () {
                        $(this).dialog("close");
                        if (btprops.callback) {
                            setTimeout(function () {
                                btprops.callback();
                            }, 0)
                        }
                    }
                });
                setButtons(i+1);
            }
        }
        setButtons(0);
    }
    

    message = message.replaceAll('\n', '<br>');
    dialogElement.find('.showPopupMessage_msg').html(message);
    var options = {
        width:width,
        classes: classes,
        resizable: true,
        modal: true,
        closeOnEscape: false,
        buttons: buttons,
        close: function () { $(this).dialog("destroy"); },
    };
    if (props)
        $.extend(options, props);

    if ($("body").is(".dir-RTL")) {
        $.extend(options, {
            position: {
                my: "center", at: "center", of: window, using: function (pos) {
                    var me = $(this);
                    me.css("right", pos.left)
                        .css("top", pos.top);
                }
            }
        });
    }
    dialogElement.dialog(options);
    return dialogElement;
}




function popupDialog(url, data, dialogOptions, ajaxCallback) {
    var dlg = $("<div><div class='loadedContent'><table width=\"100%\" height=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td valign=\"middle\" align=\"center\" class=\"small_text_b\"><img src=\"style/images/roller.gif\" class=\"roller\"></td></tr></table></div></div>");   //TODO: Get caption for Please Wait
    
    var openMethodRef = dialogOptions.open;
    var callback = ajaxCallback || onComplete;
    if (dialogOptions.autoOpen) {
        dialogOptions.open = function (event, ui) {
            $(".loadedContent", dlg).load(url, data, function (response, status, xhr) {
                applyStyle.call(dlg);
                callback.apply(dlg, arguments);
            });
            applyStyle.call(dlg.parent());
            if (openMethodRef) {
                openMethodRef(event, ui);
            }
        }
        dlg.dialog(dialogOptions);
    }
    else {
        dlg.dialog(dialogOptions);
        dlg.load(url, data,
            function(response, status, xhr) {
                applyStyle.call(dlg);
                callback.apply(dlg, arguments);
            }
        );    
    }

    function onComplete(response, status, xhr) {
        if (status != "success") {
            this.text(response);
        }
    }
    return dlg;
}

function popupFormDialog(url, data, title, btnOk, btnCancel) {
    var form;
    var dlgButtons = new Array();
    if (typeof (btnOk) != 'undefined' && btnOk !== null) {
        dlgButtons[dlgButtons.length] = {
            text: btnOk.text,
            click: function() {
                if (validateAllFields(form) && (!btnOk.click || btnOk.click())) {
                    dlg.dialog("close");
                }
            }
        };
    }
    if (typeof (btnCancel) != 'undefined' && btnCancel !== null) {
        dlgButtons[dlgButtons.length] = {
            text: btnCancel.text,
            click: function() {
                if (!btnCancel.click || btnCancel.click()) {
                    dlg.dialog("close");
                }
            }
        };
    }
    
    function onOpened(response,status,xhr){
        if (status != "success") {
            this.text(response);
        }
        else {
            form = this.find("form")[0];
            if (form)
                attachValidators(form);
        }
    }
    
    function onClose(){
        dlg.dialog("destroy");
        dlg.remove();
    }

    var dlgParams = { title: title, close: onClose, buttons: dlgButtons, modal: true };
    var dlg = popupDialog(url, data, dlgParams, onOpened);
    return dlg;
}

function popUpIframeDialog(src, title, okTitle, height, width) {
    var dlgButtons = [{
        text: okTitle,
        click: function() {
            dlg.dialog("close");
        }
    }];
    var dlgParams = { title: title, buttons: dlgButtons, height: height, width: width };
    var dlg = $("<iframe frameborder='0' src='{0}' />".format(src));
    dlg.dialog(dlgParams);
}

function setNavigationButtonStatus(button, setDisabled, explains) {
    $eSRO.req(['js/jquery-additions'], function () {
        button.EsroButton("clearExplain").EsroButton("disabled", setDisabled, explains);
    });
}
function fadeMessage(msg) {
    $("<div class='fadeMessage'>{0}</div>".format(msg))
                .appendTo('body')
                .fadeIn(700)
                .delay(2000)
                .fadeOut(700, function () {
                    $(this).remove();
                });
}
/**
** login handle
**/
function requireLogin(callback, nextPage) {
    var defaultView = "Login";
    if ($eSRO.interfaceData != null && $eSRO.interfaceData.defaultLoginView !== undefined)
        defaultView = $eSRO.interfaceData.defaultLoginView;
    loginOrRegister({ view: defaultView, oncommit: true }, callback, nextPage);
}
function login(callback, nextPage, onlyLogin) {
    loginOrRegister({ view: onlyLogin ? "OnlyLogin" : "Login" }, callback, nextPage);
}
function register(callback, nextPage) {
    loginOrRegister({ view: "Register" }, callback, nextPage);
}
function loginOrRegister(data, callback, nextPage) {
    var dlg;

    var dialogOptions = {
        modal: true,
        autoOpen:false,
        minWidth: data.view == "OnlyLogin" ? 330 : 700,
        dialogClass: 'loginOrRegisterDlg',
        close: function() {
            dlg.dialog("destroy");
            dlg.remove();
            callback && callback('', false);
        }
    };
    dlg = popupDialog($eSRO.loginOrSignupPage, data, dialogOptions, function() {
            var loginOrSignupDlg = $(this),
                container = $(".loginControl", loginOrSignupDlg),
                proceedTo = nextPage || (document.location.pathname + document.location.search);
            container.bind({
                'loginInit.esro': function (event, loginCtrl) {
                    loginCtrl.useAjax = true;
                    loginCtrl.nextPage = proceedTo;
                },
                'crmLoginComplete.esro': function (event, locationToRedirect) {
                    callback && callback('login', true, event);
                }
            });
            var form = $(document.forms["frmCreateAccount"]);
            $(form).bind("CreateAccountFormValidated.esro", function (callback2) {
                var formData = form.serialize();
                if (typeof data.oncommit != 'undefined')
                    formData += '&oncommit=' + data.oncommit;
                $.post($eSRO.loginOrSignupPage, formData, function (defaultProceedHandler) {
                    if (!callback || (callback && callback('register', true) !== false)) {
                        location.replace(proceedTo);
                    }
                }).fail(function (xhr, status, error) {
                    if (xhr.status == 302) {
                        callback && callback('register', true);
                        return;
                    }
                    logAjaxError(xhr);
                    dlg.find('.errorMessage').html(xhr.responseText);
                    form.trigger("resetForm.esro");
                });
                return false;
            });
            if (data.view == "Register") {
                var wizard = $(".loginOrRegisterWizard", loginOrSignupDlg).addClass("ajax-refreshing");
                window.setTimeout(function () {
                    wizard.removeClass("ajax-refreshing");
                }, 1000);
                //.delay(1300).removeClass("ajax-refreshing");
            }
            $(this).dialog("open");
                //.dialog("option", "position", { my: "center", at: "center", of: $('body') });
            (data.view == "Login" ? $("#username", loginOrSignupDlg) : $('.row .field>:input:visible:first', form)).focus();

    });
    return dlg;
}

function handleProceedTo(proceedTo, cancelRedirectCallback) {
    var next = proceedTo.Url ;
    if (next && next[0]!="/"){
        next = $eSRO.siteBasePath+next;
    }
    if ((proceedTo.RequiresLogin && !$eSRO.isClientLogedIn) || (proceedTo.RequiresClient && !$eSRO.hasClient)) {
        requireLogin(function(type, success) {
            if (success == true) {
                if (type == 'register') {   //login control has the logic that navigates to next target, navigating only when register was successful
                    window.location.assign(next);
                }
            }
            else {
                if (typeof cancelRedirectCallback != 'undefined') {
                    cancelRedirectCallback();
                }
            }
        }, next);
        return;
    }
    window.location.assign(next);
}

/**
* Protect window.console method calls, e.g. console is not defined on IE
* unless dev tools are open, and IE doesn't define console.debug
*/
(function() {
    if (!window.console) {
        window.console = {}; 
    }
    // union of Chrome, FF, IE, and Safari console methods
    var m = [
    "log", "info", "warn", "error", "debug", "trace", "dir", "group",
    "groupCollapsed", "groupEnd", "time", "timeEnd", "profile", "profileEnd",
    "dirxml", "assert", "count", "markTimeline", "timeStamp", "clear"
  ];
    // define undefined methods as noops to prevent errors
    for (var i = 0; i < m.length; i++) {
        if (!window.console[m[i]]) {
            window.console[m[i]] = function() { };
        }
    }
})();

var $debug = (function(con){
    function nop(){};
    return {
        log : con? con.log.bind(con) : nop,
        warn : con? con.warn.bind(con) : nop,
        error : con? con.error.bind(con) : nop,
        write : con? con.debug.bind(con) : nop,
        info : window.$debugInfo
    };
})(window.console);

function logAjaxError(xhr) {
    $debug.error("XHR Error:{0}\n{1}".format( xhr.responseText, decodeURIComponent(xhr.getResponseHeader("X-Esro-Error"))));
}

$(document).ajaxError(function(event, xhr, ajaxSettings, thrownError) {
    if (xhr.getResponseHeader("X-Esro-Session") == "closed") {
        //if (confirm("Session was closed, do you wish to refresh the page?")) {
        //    document.location.reload();
        //}
    }
});
function logClientError(ev) {
    try {
        var origEvent = ev.originalEvent;
        if (!$eSRO.api) {
            $(document).one("api.init.esro", function () {
                logClientError(ev);
            });
            return;
        }
        //var errorMsg = origEvent.error ? origEvent.error.toString() : "error is empty";
        var hash = Math.abs(origEvent.message.hashCode());
        if (window._clientErr === undefined) {
            window._clientErr = {};
        }
        if (window._clientErr[hash] === undefined) {
            window._clientErr[hash] = 1;
        }
        else {
            window._clientErr[hash]++;
            return;
        }
        $eSRO.api.call("FoundationController.LogError", {
            "errorDetails": {
                "error": origEvent.error ? origEvent.error.toString() :"error is empty",
                "location": origEvent.filename + '. line: ' + origEvent.lineno,
                "stack": origEvent.error ? encodeURI(origEvent.error.stack) : "error is empty",
                "message": origEvent.message,
                "timestamp": ev.timeStamp
            }}, undefined, undefined);
    }
    catch (e) {
        $debug.log("failed to report error: " + e.description);
    }
}
$(window).on("error", logClientError);
if (window.DD_RUM){
    window.DD_RUM.onReady(function(){
        $(window).off("error", logClientError);
    });
}


//***** Animations *****//
(function($) {
    
})(jQuery);

(function($) {
    
})(jQuery);
//***** End *****//
(function($) {
    
})(jQuery);
function applyDatePicker(className, obj) {
    require(['js/esro-ui.controls'], function () {

        var applyPickerOn;
        if (obj !== undefined) {
            applyPickerOn = obj.find("." + className);
        }
        else {
            applyPickerOn = $("." + className);
        }
        applyPickerOn.each(function (i, e) {
            var me = $(e);
            me.esrodatepicker();
            me.datepicker("setDate", me.datepicker("getDate"));
        });
    });
}

$(document).ready(function() {
    /// hack ie browser that fails to append child to body in certain cases when DivX player add-on is installed.
//    if ($.browser.msie == true && $.browser.version == '9.0') {
//        jQuery.fn.append = function() {
//            return this.domManip(arguments, true, function(elem) {
//                var me = this === document ? document.body : this;
//                if (me.nodeType === 1 && me.tagName.toLowerCase() == 'body') {
//                    me.appendChild = document.appendChild;
//                }
//                me.appendChild(elem);
//            });
//        }
//    }
    //fix IE firing widnow.beforeunload event when a link with href=void(0) is clicked

    (function fixIEVoidLinks() {
        if (!$.browser.msie) return;
        var rx = /^\s*javascript\s*\:\s*void\s*\(\s*0\s*\)\s*;?\s*$/;
        $("a").filter(function(i, e) {
            return rx.test(e.href);
        }).each(function() {
            var click = this.onclick;
            var me = this;
            if (click != null && typeof click != undefined) {
                this.onclick = function() { click.apply(me, arguments); return false; };
            }
        });
    })();
});

function getRanges() {
    var res = [], c, r, s, e;
    for (var i = 0; i < arguments.length; i++) {
        c = arguments[i];
        if (typeof (c) == "string") {
            r = c.split("-");
            if (r.length > 1) {
                s = parseInt(r[0]);
                e = parseInt(r[r.length - 1]);
                for (var j = s; j <= e; j++) {
                    res[res.length] = j.toString();
                }
                continue;
            }
        }
        res[res.length] = c;
    }
    return res;
}

/// handle please wait
var loadingHandler = (new function() {
    this.timeout = 300; //ms to wait before diplaying message
    this.dlg = null;
    var timer = null;
    var me = this;
    var disabled = null;
    var inPrevent = false;
    this.preventOnce = function() {
        inPrevent = true;
    };
    this.doShowLoading = function(message) {
        if (timer == null) return;
        timer = null;
        if (this.dlg != null)
            return;
        this.dlg = showPleaseWait(message);
    }
    this.onAjax = function(message, timeout){
        if ($("input.ui-autocomplete-input:focus").length //showing the dialog will steal the focus from the input and cause the suggestion box to close
            || $(".ajax-refreshing:visible").length //means that there is already a wait indication
            )
        {
            return null;
        }
        return this.onNavigate(message, timeout);
    }
    this.onNavigate = function(message, timeout) {
        if (!disabled && this.dlg == null && timeout!==false && !(timeout<0)) {
            if (inPrevent) {
                inPrevent = false;
                return;
            }
            if (timeout==undefined) timeout = this.timeout;
            timer = window.setTimeout(function() {
                me.doShowLoading(message);
            }, timeout);
        }
    }
    this.hideLoading = function() {
        if (this.dlg != null)
            this.dlg.dialog('close');
        this.dlg = null;
    }
    this.navigateComplete = function() {
        if (timer != null) {
            window.clearTimeout(timer);
            timer = null;
        }
        this.hideLoading();
    }
    this.init = function() {
        if (disabled == true)
            return;
        $(function() {
            $("A[href^='mailto:'], A[href^='tel:'], A[target='_new'], A[data-plzwait='prevent']").click(function() {
                me.preventOnce();
            });
        });
        $(window).on({
            'beforeunload': function() {
                me.onNavigate();
            },
            'load': function() {
                me.navigateComplete();
            }
        });
        $(document).bind({
            "ajaxSend": function(e, xhr, options) { me.onAjax(undefined, options.pleaseWaitDelay); },
            "ajaxComplete": function() { me.navigateComplete(); }
        });
        disabled = false;
        return this;
    }
    this.disable = function() {
        disabled = true;
    }
    return this;
} ()).init();

//returns a function to handle a change event of a target. If the provided fundction <fn> returns false,
//the old value is restored. Can be used in two ways:
//1. target.change(restoreIfFalse(fn)).change();
//2. target.change(restoreIfFalse(fn, target));
function restoreIfFalse(fn, target) {
    var currentVal;
    if (target != undefined) currentVal= $(target).val();
    return (function(e) {
        var me = $(this);
        var val = me.val();
        if (fn(me, val, currentVal) === false) {
            me.val(currentVal);
        } else {
            currentVal = val;
        }
    });
}
function goBack() {
    var b = $.fn.location("queryParams", "back");
    history.go(b ? -b : -1);
}
function unstringify(str){
    return str.replace(/\\['"\\nrtbf]/ig, function(m,i){return(eval("\""+m+"\""))});
}
function loadCss(url) {
    if (url.substr(0, 2) == "//") url = document.location.protocol + url;
    if ($("link[rel=stylesheet]").filter(function(i, e) {
        return e.href == url;
    }).length == 0) {
        var link = document.createElement("link");
        link.type = "text/css";
        link.rel = "stylesheet";
        link.href = url;
        document.getElementsByTagName("head")[0].appendChild(link);
    }
}
/*Make it 'global' function in order to support cancel transaction from TimeCountDown control*/
function cancelTransaction() {
    $eSRO.api.call("TransactionController.ClearBasket", { "discardTransaction": false }, undefined,
                    function(response) {
                        if (response == null)
                            return;
                        var result = null;
                        try {
                            result = response();
                        }
                        catch (ex) {
                            $debug.log('failed to update counters: {0}'.format(ex.message));
                            showPopupMessage(ex.message);
                            return;
                        }
                        location.href = $eSRO.sitePath;
                    });
}
function groupBy(coll, keyFunc, valFunc){
    var groups = {};
    $.each(coll, function(key,val){
        var group;
        key = keyFunc(key,val);
        group = groups[key];
        if (group==undefined){
            group = [];
            groups[key] = group;
        }
        group.push(valFunc ? valFunc(val) : val);
    });
    return groups;
}
function filterArray(arr, filterFunc){
    var result=[];
    for (var i=0; i<arr.length; i++){
        if (filterFunc(i, arr[i]))
            result.push(arr[i]);
    }
    return result;
}
function filterArrayByTemplate(arr, templateObj) {
    var result = [], e, equal;
    for (var i = 0; i < arr.length; i++) {
        e=arr[i];
        equal=true;
        for(k in templateObj){
            if (templateObj.hasOwnProperty(k) && e[k].valueOf() != templateObj[k].valueOf()) {
                equal=false;
                break;
            }
        };
        if (equal)
            result.push(e);
    }
    return result;
}
function getDistinct(arr, hashFunc, valFunc){
    var tmp = {};
    for (var i = 0; i < arr.length; i++) {
        tmp[hashFunc(i, arr[i])] =
            valFunc==undefined ? arr[i] : valFunc(i, arr[i]);
    }
    var result = [];
    for (key in tmp) {
        result.push(tmp[key]);
    }
    return result;
}
function getDateAsUTC(date) {
    return !date ? date : new Date(Date.UTC(
        date.getFullYear(),
        date.getMonth(),
        date.getDate(),
        date.getHours(),
        date.getMinutes(),
        date.getSeconds(),
        date.getMilliseconds()
    ));
}
function getTimezoneOffsetString(){
	var z = -(new Date()).getTimezoneOffset();
	return z==0 ? "Z" :
		(z<0?"-":"+")+f(z/60)+":"+f(z%60);
	function f(i){
	    return (100+Math.abs(i)).toString().substr(1,2);
	}
}
function calcIsDocumentWidthIsBelowThreshold() {
        return (!$eSRO.disableResponsiveness && window.matchMedia)
            ? window.matchMedia("screen and (max-width:780px)").matches
            : false;
}
function calcIsDeviceWidthIsBelowThreshold() {
        return (!$eSRO.disableResponsiveness && window.matchMedia)
            ? window.matchMedia("screen and (max-device-width:780px)").matches
            : false;
}
function calcIsLandscapeTabletAsDesktop() {
    return $eSRO.isTouchDevice && ($(window).width() >= 781 && $(window).width() <= 1024 && $(window).height() <= 780);
}
function calcIsTouchDevice() {
    var temp = 'ontouchstart' in document.documentElement ||
        'ontouchstart' in window ||
        (navigator.maxTouchPoints > 0) ||
        (navigator.msMaxTouchPoints > 0);

    return temp;
}

/*
function accessibleAlert(alertMsg) {
	//Accessibility: must create alert element. Otherwise there is a bug in NVDA screen-reader that does not read the content of javascript alert
	$('#accessibleAlert').remove();
	$('body').append('<div id="accessibleAlert" role="alert" aria-live="assertive" aria-hidden="false" aria-atomic="true" style="position:absolute; width:0; height:0; clip: rect(0,0,0,0);">' + alertMsg + '</div>');

	setTimeout(function () { $('#accessibleAlert').remove(); }, 10000);

	//Accessibility: must small timeout. Otherwise there is a bug in NVDA screen-reader that does not read also the #accessibleAlert alert
	window.setTimeout(function () {
		alert(alertMsg);
	}, 50);
}
*/

function getElementToFocus(currentElement, direction, subDomRoot, filterExcludeFromTabables) {
    if (typeof subDomRoot === "undefined" || subDomRoot === null) { 
        subDomRoot = document; 
    }

    var tabAbles = $(':tabbable', subDomRoot);
    tabAbles = tabAbles.filter(':visible');
    if (typeof filterExcludeFromTabables !== "undefined" && filterExcludeFromTabables !== null) {
    	tabAbles = tabAbles.filter(filterExcludeFromTabables);
    }

    var nextIndex = direction > 0 ? 0 : tabAbles.length - 1;

    var currentIndex = tabAbles.index(currentElement);
    if (currentIndex + direction < tabAbles.length) {
        nextIndex = currentIndex + direction;
    }
    return tabAbles.eq(nextIndex);
}

function getRegionToFocus(currentElement, direction, subDomRoot) {

    if (typeof subDomRoot === "undefined" || subDomRoot === null) { 
        subDomRoot = document; 
    }

    var focusableRegions = $(('[data-ariaLandmark]:visible'), subDomRoot).filter(function (i, e) {
    	return $('>button.skipRegion', e).is(':visible');
    });
    var nextIndex = direction > 0 ? 0 : focusableRegions.length - 1;

    var currentIndex = focusableRegions.index(currentElement);
    if (currentIndex + direction < focusableRegions.length) {
        nextIndex = currentIndex + direction;
    }
    return focusableRegions.eq(nextIndex);
}

$(window).resize(function() {
    if (window !== window.top) return;

    $.cookies.set("inMobile", $eSRO.documentWidthIsBelowThreshold);
 
    $eSRO.documentWidthIsBelowThreshold = calcIsDocumentWidthIsBelowThreshold();
    $eSRO.deviceWidthIsBelowThreshold = calcIsDeviceWidthIsBelowThreshold();
    $eSRO.isLandscapeTabletAsDesktop = calcIsLandscapeTabletAsDesktop();
    $eSRO.isTouchDevice = calcIsTouchDevice();
});
function escapeHtml(string) {
    var entityMap = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': '&quot;',
        "'": '&#39;',
        "/": '&#x2F;'
    };
    return String(string).replace(/[&<>"'\/]/g, function(s) {
        return entityMap[s];
    });
}
$eSRO.util = $.extend($eSRO.util, {
    escapeCssToken : function(token){
        return token.replace( /(:|\.|\[|\]|,|\s)/g, "\\$1" );
    },
    escapeCssValue: function(token){
        return token.replace(/[:\.\[\],'"\s\n\r\l\t]/g, function(m){
            var charCode = m.charCodeAt(0).toString(16);
            if (charCode.length==1)
                charCode="0"+charCode;
            return "\\"+charCode;
        });
    }
});
///JSON parser might return an array of single item as the item
function verifyArray(list) {
    if (typeof list.length == 'undefined' || list.constructor != Array) {
        var newlist = [];
        newlist[newlist.length] = list;
        list = newlist;
    }
    return list;
}
(function(jQuery){ //restore $.browser that was removed in jQuery 1.9.0
    if ( !jQuery.browser ) {
        var ua = navigator.userAgent.toLowerCase();

	    var match = /(chrome)[ \/]([\w.]+)/.exec( ua ) ||
		    /(webkit)[ \/]([\w.]+)/.exec( ua ) ||
		    /(opera)(?:.*version|)[ \/]([\w.]+)/.exec( ua ) ||
		    /(msie) ([\w.]+)/.exec( ua ) ||
		    ua.indexOf("compatible") < 0 && /(mozilla)(?:.*? rv:([\w.]+)|)/.exec( ua ) ||
		    [];

	    var matched = {
		    browser: match[ 1 ] || "",
		    version: match[ 2 ] || "0"
	    };
	    
	    var browser = {};

	    if ( matched.browser ) {
		    browser[ matched.browser ] = true;
		    browser.version = matched.version;
	    }

	    // Chrome is Webkit, but Webkit is also Safari.
	    if ( browser.chrome ) {
		    browser.webkit = true;
	    } else if ( browser.webkit ) {
		    browser.safari = true;
	    }

	    jQuery.browser = browser;
    }
})(jQuery);


function showResalePrompt() {
    require(['modernizr'], function (modernizr) {
        var checkedResaleInThisSession;
        if (modernizr.localstorage) {
            if ($eSRO.isClientLogedIn) {
                checkedResaleInThisSession = localStorage["esro.checkedResaleInThisSession"] == "true"
                    && localStorage["esro.thisSessionId"] === $eSRO.getAntiCsrfToken(); //can use this as session id because it's unique per session 
                if (!checkedResaleInThisSession) {
                    require(["js/crmAlertItems"], function (crmAlertItems) {
                        crmAlertItems.showCrmAlertItemsDialog(function() {
                            localStorage["esro.checkedResaleInThisSession"] = "true";
                            localStorage["esro.thisSessionId"] = $eSRO.getAntiCsrfToken();
                        });
                    });
                }
            } else {
                localStorage["esro.checkedResaleInThisSession"] = "false";
            }
        }
    });
}
//-------------------------------------------------------------------------------------------------------------
/// override some JQuery UI for accessibility
if ($.datepicker) {

    function setMonthAndYearLabels(htmlObj) {
    	require(["js/res!js/jquery-ui-overrides.res"], function (res) {

    		$('.ui-datepicker-prev:not(.ui-state-disabled)', htmlObj).attr('tabindex', '0').attr("aria-label", res.Captions["eSRO_ARIA_CalendarPrevMonth"]);
    		$('.ui-datepicker-next:not(.ui-state-disabled)', htmlObj).attr('tabindex', '0').attr("aria-label", res.Captions["eSRO_ARIA_CalendarNextMonth"]);

    		//Accessibility bug: ENTER not trigger the click even though it is a link href
    		$('.ui-datepicker-prev:not(.ui-state-disabled),.ui-datepicker-next:not(.ui-state-disabled)', htmlObj).on('keydown', function (e) {
    			if (e.which == 13) {
    				$(e.target).click();
    			}
    		});

    		$("select.ui-datepicker-month", htmlObj).attr('aria-label', res.Captions["eSRO_ARIA_Label_SelectMonth"]);
    		$("select.ui-datepicker-year", htmlObj).attr('aria-label', res.Captions["eSRO_ARIA_Label_SelectYear"]);
        });
    }
    setMonthAndYearLabels($(document));
    var orig_generateMonthYearHeader = $.datepicker._generateMonthYearHeader;
    $.datepicker._generateMonthYearHeader = function (inst, drawMonth, drawYear, minDate, maxDate,
            secondary, monthNames, monthNamesShort) {
        var html = orig_generateMonthYearHeader.call(this, inst, drawMonth, drawYear, minDate, maxDate,
            secondary, monthNames, monthNamesShort);
        var htmlObj = $("<div>").append(html);
        setMonthAndYearLabels(htmlObj);
        return htmlObj.html();
    }


}
define('esro.util', ['jquery'], function ($) {
    var regexStripComments = /(\/\/.*$)|(\/\*[\s\S]*?\*\/)|(\s*=[^,\)]*(('(?:\\'|[^'\r\n])*')|("(?:\\"|[^"\r\n])*"))|(\s*=[^,\)]*))/mg;
    var regexArgNames = /([^\s,]+)/g;

    return {
        formatAsArray: function () { //returns formatted string as array
            var input = this, args=arguments;
            var str = input, match, arr = [];
            while ((match = (/{(\d+)}/g).exec(str)) != null) {
                arr.push(str.substr(0, match.index));
                arr.push(args[parseInt(match[1])]);
                str = str.substr(match.index + match[0].length);
            }
            if (str != "") {
                arr.push(str);
            }
                
            return arr;
        },
        html2text: function (element) {
            var node, text = "", html2text=arguments.callee;
            for (var i=0; i<element.childNodes.length; i++) {
                node = element.childNodes[i];
                if (node.nodeType == 3) {//text
                    text += node.nodeValue;
                } if (node.tagName == "BR") {
                    text += "\n";
                } else if (node.nodeType == 1) {
                    var res = html2text(node);
                    if ($(node).css("display") == "block") {
                        text += "\n" + res + "\n";
                    } else {
                        text += res;
                    }
                }
            }
            return text;
        },
        /**
         * Allows handlers to chain multiple callbacks
         * @constructor
         */
        ChainedCallback: function () {
            var callbacks = [];

            /*
             * Executes all the callbacks in the chain
             * @return {promise} The promise that is resolved when all the callbacks succeed or rejected when one of the callbacks fails. The resolution value is the one returned by the last callback in the chain
             */
            this.execute = function () {
                if (callbacks.length == 0) {
                    var ret = $.Deferred();
                    ret.resolve();
                    return ret;
                } else {
                    return exec(0);
                }

                function exec(i) {
                    var promise = callbacks[i]();
                    if (!promise || typeof (promise.then) != "function") { //if not thenable, use a resolved promise
                        promise = $.Deferred();
                        promise.resolve();
                    }
                    i++;
                    if (i<callbacks.length){
                        return promise.then(function () {
                            return exec(i);
                        });
                    }else{
                        return promise;
                    }
                }
            }

            /**
             * Appends a callback to the chain
             * @param {function():promise} callback - The callback to append
             */
            this.append = function (callback) {
                //lastPromise = lastPromise.then(function () { return callback(); });
                callbacks.push(callback);
            };

            /**
            * prepends a callback to the chain
            * @param {function():promise} callback - The callback to prepends
            */
            this.prepend = function (callback) {
                callbacks.splice(0, 0, callback);
            }

            return this;
        },
        normalizeSpaces:function(str) {
            return str.replace(/(^\s+)|(\s+$)/g, "").replace(/\s{2,}/g, " ");
        }
    }
});
require(['esro.util']);

//POLYFILLS
(function(){
    if (!HTMLFormElement.prototype.reportValidity) {
        HTMLFormElement.prototype.reportValidity = function() {
            if (this.checkValidity()) return true;
            var btn = document.createElement('button');
            this.appendChild(btn);
            btn.click();
            this.removeChild(btn);
            return false;
        };
    }

    function inputReportValidityPolyfill(){
        if (this.checkValidity()) return true;
        var tmpForm;
        if (!this.form) {
            var tmpForm = document.createElement('form');
            tmpForm.style.display = 'inline';
            this.before(tmpForm);
            tmpForm.append(this);
        }
        var input, i, siblings = [];

        for(i=0; i<this.form.elements.length; i++){
            input = this.form.elements[i]; 
            if (input !== this && !!input.checkValidity && !input.disabled && input.nodeName!=="FIELDSET"){
                input.disabled = true;
                siblings.push(input);
            }
        }
                
        this.form.reportValidity();
        for(var i=0; i<siblings.length; i++){
            input = siblings[i];
            input.disabled = false;
        }
        if (tmpForm) {
            tmpForm.before(this);
            tmpForm.remove();
        }
        this.focus();
        this.selectionStart = 0;


        return false;
    }
    
    if (!HTMLInputElement.prototype.reportValidity) {
        HTMLInputElement.prototype.reportValidity = inputReportValidityPolyfill;
    }
    if (!HTMLSelectElement.prototype.reportValidity) {
        HTMLSelectElement.prototype.reportValidity = inputReportValidityPolyfill;
    }
})();

require(['js/jquery-additions'],function(){
  //var params = new URLSearchParams(document.location.search);
  //if (params.has("_req_repeat"))
  //{
  //  params.delete("_req_repeat");
  //  history.pushState(undefined, undefined, window.location.pathname + (params.size>0 ? "?"+params.toString() : "" ) );
  //}
  var params = $.fn.location("queryParams");
  if ("_req_repeat" in params){
    delete params._req_repeat;
    history.pushState(undefined, undefined, window.location.pathname + ($.isEmptyObject(params) ? "" : "?"+$.fn.location("serializeParams", params)));
  }
});