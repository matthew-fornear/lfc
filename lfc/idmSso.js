define("idmSso", ["module"], function(module) {
  "use strict";
  var config = module.config(),
    uiUrl = config["uiUrl"],
    manageRelationshipsEndpoint = config["manageRelationshipsEndpoint"],
    changePasswordUrl = config["changePasswordUrl"],
    requestFullProfile = config["requestFullProfile"] == "true",
    sroManagesRelationships = config["sroManagesRelationships"] == "true",
    isSaSsoCompatible = config["isSaSsoCompatible"] == "true",
    clientId = config["clientId"];

  /*(1) For Lite Profile clicking “Edit” would display the default eSRO edit dialog
      (2) On(ChangeSsoPassword.spCommandExecuting.esro) is new button was added to eCRM by the next screen part:
                                            eSRO.Crm.PersonalDetailsView.spscreen*/
  $(document)
    .on(
      "ChangePassword.spCommandExecuting.esro",
      "*[data-screenname=eSRO\\.Crm\\.PersonalDetailsView]",
      onOldChangePasswordBtn
    )
    .on(
      "ContactMe.spCommandExecuting.esro MyPreferences.spCommandExecuting.esro",
      "*[data-screenname=eSRO\\.Crm\\.PersonalDetailsView]",
      isSaSsoCompatible ? goToIdpUpdatePreferencesPage : goToIdpProfilePage
    )
    .on(
      requestFullProfile ? "EditPersonalDetails.spCommandExecuting.esro" : "",
      "*[data-screenname=eSRO\\.Crm\\.PersonalDetailsView]",
      goToIdpProfilePage
    )
    .on(
      "ChangeSsoPassword.spCommandExecuting.esro",
      "*[data-screenname=eSRO\\.Crm\\.PersonalDetailsView]",
      goToIdpChangePasswordPage
    );

  $eSRO.api.bind("beforeLogoutClient.CrmController", function(e) {
    var loc = document.location,
      base = $eSRO.siteBasePath,
      targetUrl = config["currentPageRequiresClient"]
        ? ""
        : loc.pathname.substr(base.length) + loc.search,
      //logoutUrl = "https://" + loc.host + base + "SaSso?act=logout&next={0}".format(encodeURIComponent(targetUrl)),
      href =
        base + "idmSso/logout?next={0}".format(encodeURIComponent(targetUrl));
    loc.href = href;
    return false;
  });

  function onOldChangePasswordBtn(e) {
    if (e !== undefined) {
      e.stopImmediatePropagation();
      e.preventDefault();
    }
    throw "Not implemented";
  }

  function goToIdpProfilePage(e) {
    if (e !== undefined) {
      e.stopImmediatePropagation();
      e.preventDefault();
    }

    var loc = document.location,
      base = $eSRO.siteBasePath,
      relTargetUrl,
      ssoLoginUrlFormat = base + "idmSso/auth?act={0}&next={1}";

    relTargetUrl = loc.pathname.substr(base.length) + loc.search;

    loc.href = ssoLoginUrlFormat.format(
      "update",
      encodeURIComponent(relTargetUrl)
    );
  }

  function goToIdpUpdatePreferencesPage(e) {
    if (e !== undefined) {
      e.stopImmediatePropagation();
      e.preventDefault();
    }

    if (isSaSsoCompatible) {
      var loc = document.location,
        base = $eSRO.siteBasePath,
        relTargetUrl,
        ssoLoginUrlFormat = base + "idmSso/auth?act={0}&next={1}";

      relTargetUrl = loc.pathname.substr(base.length) + loc.search;

      loc.href = ssoLoginUrlFormat.format(
        "updatePreferences",
        encodeURIComponent(relTargetUrl)
      );
    }
  }

  function goToIdpChangePasswordPage(e) {
    if (e !== undefined) {
      e.stopImmediatePropagation();
      e.preventDefault();
    }

    if (!isSaSsoCompatible) {
      document.location.href =
        changePasswordUrl +
        "?returnUrl=" +
        encodeURIComponent(document.location.href);
    } else {
      document.location.href =
        changePasswordUrl +
        "?mandatory=true" +
        "&tenantid=" +
        clientId +
        "&successredirecturl=" +
        encodeURIComponent(document.location.href) +
        "&returnvisitorurl=" +
        encodeURIComponent(document.location.href);
    }
  }

  function gotoSso(act, targetUrl) {
    var loc = document.location,
      base = $eSRO.siteBasePath,
      relTargetUrl,
      absTargetUrl,
      ssoLoginUrlFormat = base + "idmSso/auth?act={0}&next={1}";

    if (!targetUrl) {
      relTargetUrl = loc.pathname.substr(base.length) + loc.search;
      //absTargetUrl = loc.href;
    } else {
      relTargetUrl = targetUrl;
      if (relTargetUrl.substr(0, base.length) == base) {
        relTargetUrl = relTargetUrl.substr(base.length);
      }
      //absTargetUrl = rel2abs(targetUrl);
    }
    if (
      relTargetUrl.substr(0, "linkcustomer.aspx".length).toLowerCase() ==
      "linkcustomer.aspx"
    ) {
      relTargetUrl = "";
      //absTargetUrl = rel2abs("");
    }

    loc.href = ssoLoginUrlFormat.format(act, encodeURIComponent(relTargetUrl));
  }

  //function rel2abs(url) {
  //    if (url.substr(0, 1) != "/") url = $eSRO.siteBasePath + url;
  //    return document.location.protocol + "//" + document.location.host + url;
  //}

  var sso = {
    register: function() {
      gotoSso("register");
    },
    login: function() {
      gotoSso("login");
    },
    gotoSso: gotoSso
  };

  //TODO: Maybe find a more elegant solution? Maybe add a hook in eSRO?
  window.loginOrRegister = function(data, callback, nextPage) {
    if (data.view === "Register") {
      gotoSso("register", nextPage);
    } else {
      gotoSso("login", nextPage);
    }
  };

  if (!sroManagesRelationships) {
    require(["js/CrmEditRelationshipsDialog"], function(module) {
      module.initiatedPromise.then(function() {
        onInitialized.apply(undefined, arguments);
      });
      function onInitialized(
        container,
        url,
        customerIdToken,
        relationshipTypes,
        relationshipData
      ) {
        if (!container.data("reloadEventAttached")) {
          container
            .on("reload.esro", function() {
              module.initiatedPromise.then(function() {
                onInitialized.apply(undefined, arguments);
              });
            })
            .data("reloadEventAttached", true);
        }

        var currentWindow;
        var link = $("a.create", container);
        link.off("click");
        link.on("click", function(e) {
          //e.stopImmediatePropagation();
          var origin = uiUrl;
          if (origin.substr(-1) == "/") {
            origin = origin.substr(0, origin.length - 1);
          }

          var e = $("<div>", { id: "idm-ff-window" }).appendTo("body"),
            width = e.width(),
            height = e.height(),
            left = window.screenX + window.outerWidth / 2 - width / 2,
            top = window.screenY + window.outerHeight / 2 - height / 2;
          e.remove();

          /*Code to fix a situation defined in the parameter:
                    manageRelationshipsEndpoint = "/friends-and-family/"
                    instead of:
                    manageRelationshipsEndpoint="friends-and-family"*/

          manageRelationshipsEndpoint = "/" + manageRelationshipsEndpoint + "/";
          manageRelationshipsEndpoint = manageRelationshipsEndpoint.replace(
            "//",
            "/"
          );

          currentWindow = window.open(
            origin + manageRelationshipsEndpoint,
            "idm-ff",
            "width=" +
              width +
              ",height=" +
              height +
              ",resizable,top=" +
              top +
              ",left=" +
              left
          );
          var win = $(window);
          win.off("message.idmSso");
          var handler = $.proxy(onMessage, undefined, currentWindow, origin);
          win.on(
            "message.idmSso",
            {
              done: function() {
                win.off("message.idmSso", handler);
              }
            },
            handler
          );
        });

        function onMessage(windowObj, origin, e) {
          if (windowObj != currentWindow) return;
          var ev = e.originalEvent;
          if (ev.origin == origin) {
            var data = ev.data;
            if (data.type != "Find" && data.type != "Create") return;
            e.data.done();

            $.ajax({
              url: $eSRO.siteBasePath + "idmSso/related",
              method: "POST",
              data: data
            }).then(
              function(result, status, xhr) {
                //$("#lookupCustomer [name=crmId]", container).val(result.crmId);
                //$("#lookupCustomer [name=lastName]", container).val(result.lastName);
                //$("#lookupCustomer [name=zipCode]", container).val(result.zipCode);
                //$("button.find", container).click();
                var query,
                  idx = url.indexOf("?");
                if (idx >= 0) {
                  url = url.substr(0, idx);
                  query = url.substring(idx, url.length);
                } else {
                  query = "";
                }
                url += $.fn.location("extendQuery", query, { op: "create" });
                var data = {
                  csrfToken: $eSRO.getAntiCsrfToken(),
                  customerId: result.customerId,
                  relatedCustomerId: result.relatedCustomerId,
                  relationshipType: result.relationshipType,
                  "relationshipRole-left": result.relationshipRoleLeft,
                  "relationshipRole-right": result.relationshipRoleRight,
                  isStrongRelationship: result.relationshipIsStrong
                    ? "true"
                    : undefined
                };
                var containerParent = container.parent();
                module.loadContent(container, url, data, function(
                  response,
                  status,
                  xhr
                ) {
                  if (status == "error") {
                    showPopupMessage(xhr.responseText);
                  } else {
                    container = containerParent.find(
                      "#editRelationshipsContainer"
                    );
                    container.trigger("dataChanged.esro");
                  }
                });
              },
              function(xhr, error) {
                showPopupMessage(xhr.responseText);
              }
            );
          }
        }
      }
    });
  }

  return sso;
});
