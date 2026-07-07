import Toybox.Application;
import Toybox.Communications;
import Toybox.Lang;

// Fetches the compact briefing from the backend and caches the last good copy
// in persistent Storage, so a view can render immediately and degrade
// gracefully to a "Stale"/"Offline" state when the backend is unreachable.
class BriefingClient {
    var data;      // Dictionary or null (the last payload we have)
    var status;    // String status shown while there's no data
    var loading;   // Boolean guard against overlapping requests
    var onData;    // Method invoked whenever data/status changes

    function initialize(onDataCb) {
        onData = onDataCb;
        loading = false;
        var cached = Application.Storage.getValue("briefing");
        if (cached instanceof Lang.Dictionary) {
            data = cached;
            status = "Cached";
        } else {
            data = null;
            status = "Loading...";
        }
    }

    function fetch() {
        if (loading) {
            return;
        }
        var url = Application.Properties.getValue("apiUrl");
        if (url == null || !(url instanceof Lang.String) || url.length() == 0) {
            status = "Set apiUrl in settings";
            notify();
            return;
        }
        loading = true;
        if (data == null) {
            status = "Loading...";
        }
        notify();

        var params = {};
        var token = Application.Properties.getValue("apiToken");
        if (token != null && token instanceof Lang.String && token.length() > 0) {
            params.put("token", token);
        }
        var options = {
            :method => Communications.HTTP_REQUEST_METHOD_GET,
            :responseType => Communications.HTTP_RESPONSE_CONTENT_TYPE_JSON
        };
        var base = url as Lang.String;
        Communications.makeWebRequest(base + "/api/watch/briefing", params, options, method(:onResponse));
    }

    function onResponse(
        code as Lang.Number,
        resp as Null or Lang.Dictionary or Lang.String or Toybox.PersistedContent.Iterator
    ) as Void {
        loading = false;
        if (code == 200 && resp instanceof Lang.Dictionary) {
            data = resp;
            status = "OK";
            Application.Storage.setValue("briefing", resp);
        } else if (data != null) {
            status = "Stale (" + code + ")";
        } else {
            status = "Offline (" + code + ")";
        }
        notify();
    }

    function notify() {
        if (onData != null) {
            onData.invoke();
        }
    }
}
