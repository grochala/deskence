// SPDX-License-Identifier: GPL-3.0-or-later
//
// When a "keep awake" session ends, without GNOME Shell imports so it can
// be tested (tests/unit/test_keep_awake.js).
//
// A duration is measured on the monotonic clock (microseconds), so
// changing the system clock or the time zone does not shorten or extend
// it. "Until a time" is the next occurrence of that local wall-clock time
// and is checked against the wall clock, so it follows clock changes and
// daylight saving time.

export const CHOICES = ['indefinite', '15', '30', '60', 'custom', 'until'];

// The next local occurrence of minutesOfDay (0..1439) after now (a Date);
// today when still ahead, otherwise tomorrow.
export function nextOccurrence(now, minutesOfDay) {
    const hours = Math.floor(minutesOfDay / 60);
    const minutes = minutesOfDay % 60;
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate(), hours, minutes);
    if (today > now)
        return today;
    return new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, hours, minutes);
}

// The end of a session started now: {kind: 'indefinite'},
// {kind: 'duration', end (monotonic µs), minutes} or {kind: 'until', end
// (ms since the epoch)}.
export function plan(choice, {now, monotonic, customMinutes, untilMinutes}) {
    switch (choice) {
    case '15':
    case '30':
    case '60':
        return {kind: 'duration', minutes: Number(choice), end: monotonic + Number(choice) * 60e6};
    case 'custom':
        return {kind: 'duration', minutes: customMinutes, end: monotonic + customMinutes * 60e6};
    case 'until':
        return {kind: 'until', end: nextOccurrence(now, untilMinutes).getTime()};
    default:
        return {kind: 'indefinite'};
    }
}

// Seconds left, 0 when over, null without an end.
export function remaining(session, {now, monotonic}) {
    if (session.kind === 'duration')
        return Math.max(0, Math.ceil((session.end - monotonic) / 1e6));
    if (session.kind === 'until')
        return Math.max(0, Math.ceil((session.end - now.getTime()) / 1000));
    return null;
}

// Rounded up, so "1 minute left" lasts until the end.
export function minutesLeft(seconds) {
    return Math.ceil(seconds / 60);
}

export function formatTime(minutesOfDay) {
    const h = Math.floor(minutesOfDay / 60);
    const m = minutesOfDay % 60;
    return `${h}:${String(m).padStart(2, '0')}`;
}

// Steps of the duration and time adjusters in the menu.
export function stepMinutes(value, delta, min, max, wrap = false) {
    let result = value + delta;
    if (wrap)
        return ((result % (max + 1)) + max + 1) % (max + 1);
    result = Math.min(max, Math.max(min, result));
    return result;
}
