import Toybox.Lang;
import Toybox.Graphics;

// Shared, dependency-free helpers used by both the app view and the glance.
// Unannotated with (:glance), so they're available in every build scope.

const PAGE_COUNT = 4;

// Object? -> printable String (nulls become a dash).
function str(v) as Lang.String {
    if (v == null) {
        return "--";
    }
    return v.toString();
}

// Readiness traffic-light band -> color.
function bandColor(band as Lang.String) as Lang.Number {
    if (band.equals("green")) {
        return Graphics.COLOR_GREEN;
    } else if (band.equals("yellow")) {
        return Graphics.COLOR_YELLOW;
    } else if (band.equals("red")) {
        return Graphics.COLOR_RED;
    }
    return Graphics.COLOR_LT_GRAY;
}

// Heat-advisory severity -> color.
function heatColor(sev as Lang.String) as Lang.Number {
    if (sev.equals("extreme") || sev.equals("high")) {
        return Graphics.COLOR_RED;
    } else if (sev.equals("moderate") || sev.equals("low")) {
        return Graphics.COLOR_YELLOW;
    }
    return Graphics.COLOR_GREEN;
}

// Truncate to fit a small screen (drawText does not wrap).
function shorten(text as Lang.String, maxLen as Lang.Number) as Lang.String {
    if (text.length() <= maxLen) {
        return text;
    }
    return text.substring(0, maxLen - 2) + "..";
}
