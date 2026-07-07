import Toybox.WatchUi;
import Toybox.Graphics;
import Toybox.Lang;

// The full app: four swipeable pages driven by one BriefingClient.
//   0 Readiness   1 Recovery   2 Conditions   3 Goal Event
class WaypointView extends WatchUi.View {
    hidden var mClient;
    hidden var mPage;

    function initialize() {
        View.initialize();
        mPage = 0;
        mClient = new BriefingClient(method(:onData));
    }

    function onShow() {
        mClient.fetch();
    }

    // BriefingClient callback -> repaint.
    function onData() {
        WatchUi.requestUpdate();
    }

    function refresh() {
        mClient.fetch();
    }

    function nextPage() {
        mPage = (mPage + 1) % PAGE_COUNT;
        WatchUi.requestUpdate();
    }

    function prevPage() {
        mPage = (mPage + PAGE_COUNT - 1) % PAGE_COUNT;
        WatchUi.requestUpdate();
    }

    function onUpdate(dc) {
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_BLACK);
        dc.clear();
        var cx = dc.getWidth() / 2;
        var d = mClient.data;
        if (d == null) {
            drawTitle(dc, cx, "Waypoint");
            center(dc, cx, dc.getHeight() / 2, Graphics.FONT_SMALL, Graphics.COLOR_LT_GRAY, mClient.status);
            return;
        }
        if (mPage == 0) {
            pageReadiness(dc, cx, d);
        } else if (mPage == 1) {
            pageRecovery(dc, cx, d);
        } else if (mPage == 2) {
            pageConditions(dc, cx, d);
        } else {
            pageEvent(dc, cx, d);
        }
        pager(dc, cx, dc.getHeight());
    }

    // ---- pages ----

    hidden function pageReadiness(dc, cx, d) {
        var h = dc.getHeight();
        drawTitle(dc, cx, "Readiness");
        var band = str(d.get("readiness_band"));
        var score = d.get("readiness_score");
        var color = bandColor(band);
        center(dc, cx, h * 0.42, Graphics.FONT_NUMBER_HOT, color, (score == null) ? "--" : score.toString());
        center(dc, cx, h * 0.66, Graphics.FONT_TINY, color, band.toUpper());
        center(dc, cx, h * 0.82, Graphics.FONT_XTINY, Graphics.COLOR_LT_GRAY, shorten(str(d.get("action")), 30));
    }

    hidden function pageRecovery(dc, cx, d) {
        var h = dc.getHeight();
        drawTitle(dc, cx, "Recovery");
        var pct = d.get("recovery_pct");
        center(dc, cx, h * 0.44, Graphics.FONT_NUMBER_MEDIUM, Graphics.COLOR_WHITE, (pct == null) ? "--" : pct.toString() + "%");
        center(dc, cx, h * 0.66, Graphics.FONT_XTINY, Graphics.COLOR_LT_GRAY, "recovered");
        center(dc, cx, h * 0.80, Graphics.FONT_TINY, Graphics.COLOR_WHITE, "Next: " + str(d.get("next_intensity")));
    }

    hidden function pageConditions(dc, cx, d) {
        var h = dc.getHeight();
        drawTitle(dc, cx, "Conditions");
        var temp = d.get("temp_high_f");
        var dew = d.get("dew_point_f");
        var sev = str(d.get("heat_severity"));
        center(dc, cx, h * 0.42, Graphics.FONT_MEDIUM, Graphics.COLOR_WHITE, ((temp == null) ? "--" : temp.toString()) + "F");
        center(dc, cx, h * 0.60, Graphics.FONT_XTINY, Graphics.COLOR_LT_GRAY, "dew " + ((dew == null) ? "--" : dew.toString()));
        center(dc, cx, h * 0.78, Graphics.FONT_TINY, heatColor(sev), "heat: " + sev);
    }

    hidden function pageEvent(dc, cx, d) {
        var h = dc.getHeight();
        drawTitle(dc, cx, "Goal Event");
        var days = d.get("event_days");
        if (days == null) {
            center(dc, cx, h / 2, Graphics.FONT_SMALL, Graphics.COLOR_LT_GRAY, "No event set");
            return;
        }
        center(dc, cx, h * 0.44, Graphics.FONT_NUMBER_MEDIUM, Graphics.COLOR_WHITE, days.toString());
        center(dc, cx, h * 0.64, Graphics.FONT_XTINY, Graphics.COLOR_LT_GRAY, "days to go");
        center(dc, cx, h * 0.80, Graphics.FONT_XTINY, Graphics.COLOR_WHITE, shorten(str(d.get("event_name")), 22));
    }

    // ---- drawing helpers ----

    hidden function drawTitle(dc, cx, t) {
        center(dc, cx, dc.getHeight() * 0.15, Graphics.FONT_XTINY, Graphics.COLOR_LT_GRAY, t);
    }

    hidden function pager(dc, cx, h) {
        center(dc, cx, h * 0.93, Graphics.FONT_XTINY, Graphics.COLOR_DK_GRAY,
            (mPage + 1).toString() + "/" + PAGE_COUNT.toString());
    }

    hidden function center(dc, x, y, font, color, text) {
        dc.setColor(color, Graphics.COLOR_TRANSPARENT);
        dc.drawText(x, y, font, text, Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
    }
}
