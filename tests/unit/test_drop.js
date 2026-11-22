// SPDX-License-Identifier: GPL-3.0-or-later
// Run with: gjs -m tests/unit/test_drop.js
import System from 'system';

import {Cleanup, appAccepts, edgeScrollStep, isDropEnd, isFileUri, isWithin, offersFiles, parentUri, parseUriList,
    planKind, planTransfer, transferAction}
    from '../../extensions/dock/dropLogic.js';

let failures = 0;
function check(name, condition) {
    if (!condition) {
        failures++;
        printerr(`FAIL: ${name}`);
    } else {
        print(`ok: ${name}`);
    }
}
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// --- Drag data --------------------------------------------------------------

check('files offered', offersFiles(['text/plain', 'text/uri-list']));
check('text only is no file drag', !offersFiles(['text/plain', 'UTF8_STRING']) &&
    !offersFiles([]) && !offersFiles(null));
check('uri list with CRLF and comments', same(
    parseUriList('# from Files\r\nfile:///home/u/a.txt\r\nfile:///home/u/b%20c.txt\r\n'),
    ['file:///home/u/a.txt', 'file:///home/u/b%20c.txt']));
check('uri list with LF, blanks and duplicates', same(
    parseUriList('\nfile:///a\n\n  file:///b  \nfile:///a\n'), ['file:///a', 'file:///b']));
check('lines that are not URIs dropped', same(
    parseUriList('/home/u/a.txt\nrelative/b\nsftp://host/c\n'), ['sftp://host/c']));
check('no data', same(parseUriList(''), []) && same(parseUriList(null), []));

// --- Paths ------------------------------------------------------------------

check('folder within itself', isWithin('file:///home/u/A', 'file:///home/u/A') &&
    isWithin('file:///home/u/A/', 'file:///home/u/A'));
check('subfolder within', isWithin('file:///home/u/A/B/C', 'file:///home/u/A'));
check('sibling with a common prefix is not within', !isWithin('file:///home/u/AB', 'file:///home/u/A'));
check('everything within the root', isWithin('file:///etc', 'file:///'));
check('parent of a file', parentUri('file:///home/u/a.txt') === 'file:///home/u');
check('parent of a folder with a slash', parentUri('file:///home/u/A/') === 'file:///home/u');
check('parent at the root', parentUri('file:///a') === 'file:///' && parentUri('file:///') === null);
check('parent on a remote host', parentUri('sftp://host/srv/a') === 'sftp://host/srv' &&
    parentUri('sftp://host/a') === 'sftp://host/' && parentUri('sftp://host') === null);
check('no path', parentUri('mailto:someone') === null);

// --- Copy or move -----------------------------------------------------------

check('same file system moves', transferAction({}, true) === 'move');
check('other file system copies', transferAction({}, false) === 'copy');
check('unknown file system copies', transferAction({}, null) === 'copy');
check('Ctrl copies', transferAction({ctrl: true}, true) === 'copy');
check('Shift moves', transferAction({shift: true}, false) === 'move');
check('Shift wins over Ctrl, as in mutter', transferAction({shift: true, ctrl: true}, false) === 'move');

const downloads = {uri: 'file:///home/u/Downloads', available: true, writable: true};
const src = (uri, sameFilesystem = true) => ({uri, sameFilesystem});

check('move within a file system', same(
    planTransfer([src('file:///home/u/Desktop/a.txt')], downloads),
    {copy: [], move: ['file:///home/u/Desktop/a.txt']}));
check('copy from a USB stick', same(
    planTransfer([src('file:///run/media/u/STICK/a.txt', false)], downloads),
    {copy: ['file:///run/media/u/STICK/a.txt'], move: []}));
check('mixed sources', planKind(planTransfer([src('file:///home/u/a'),
    src('file:///run/media/u/S/b', false)], downloads)) === 'mixed');
check('Ctrl copies everything', planKind(planTransfer([src('file:///home/u/a')], downloads,
    {ctrl: true})) === 'copy');
check('web links are not files', planTransfer([{uri: 'https://example.com/a.iso', isFile: false}],
    downloads).refused === 'not-files');
const schemes = ['file', 'sftp', 'smb', 'http', 'https'];
check('file URIs', isFileUri('file:///a', schemes) && isFileUri('SFTP://host/a', schemes));
check('web and unknown schemes', !isFileUri('https://x/a', schemes) && !isFileUri('http://x', schemes) &&
    !isFileUri('mtp://x/a', schemes) && !isFileUri('noscheme', schemes));
check('nothing dragged', planTransfer([], downloads).refused === 'nothing');
check('missing or unmounted folder', planTransfer([src('file:///home/u/a')],
    {uri: 'file:///run/media/u/GONE', available: false}).refused === 'unavailable');
check('read-only folder', planTransfer([src('file:///home/u/a')],
    {uri: 'file:///usr/share', available: true, writable: false}).refused === 'read-only');
check('unknown writability is tried (Files reports errors)', !planTransfer(
    [src('file:///home/u/a')], {uri: 'file:///srv/x', available: true, writable: null}).refused);
check('folder into itself', planTransfer([src('file:///home/u/Downloads')], downloads)
    .refused === 'into-itself');
check('folder into its subfolder', planTransfer([src('file:///home/u')],
    {...downloads}).refused === 'into-itself');
check('copy into itself refused too', planTransfer([src('file:///home/u/Downloads')], downloads,
    {ctrl: true}).refused === 'into-itself');
check('moving to the same folder does nothing', planTransfer(
    [src('file:///home/u/Downloads/a.txt')], downloads).refused === 'already-there');
check('copying in the same folder is allowed (Files names the copy)', same(planTransfer(
    [src('file:///home/u/Downloads/a.txt')], downloads, {ctrl: true}),
{copy: ['file:///home/u/Downloads/a.txt'], move: []}));
check('files already there are left out of a move', same(planTransfer(
    [src('file:///home/u/Downloads/a.txt'), src('file:///home/u/b.txt')], downloads),
{copy: [], move: ['file:///home/u/b.txt']}));
check('refused plan has no kind', planKind({refused: 'read-only'}) === null);

// --- Applications -----------------------------------------------------------

const local = [{uri: 'file:///home/u/a.txt', hasPath: true}];
const remote = [{uri: 'sftp://host/a.txt', hasPath: false}];
check('%U takes any URI', appAccepts({supportsUris: true, supportsFiles: true}, remote) === 'uris');
check('%F takes local files', appAccepts({supportsUris: false, supportsFiles: true}, local) === 'files');
check('%F refuses files without a path', appAccepts({supportsUris: false, supportsFiles: true},
    [...local, ...remote]) === null);
check('no field code takes nothing', appAccepts({supportsUris: false, supportsFiles: false},
    local) === null);
check('no application or no files', appAccepts(null, local) === null &&
    appAccepts({supportsUris: true}, []) === null);

// --- Scrolling and the end of a drag ---------------------------------------

check('no scrolling in the middle', edgeScrollStep(150, 300, 40, 12) === 0);
check('scrolling up near the top, faster at the edge',
    edgeScrollStep(30, 300, 40, 12) < 0 && edgeScrollStep(1, 300, 40, 12) < edgeScrollStep(30, 300, 40, 12));
check('scrolling down near the bottom', edgeScrollStep(290, 300, 40, 12) > 0);
check('edge step never exceeds the maximum', edgeScrollStep(0, 300, 40, 12) === -12 &&
    edgeScrollStep(300, 300, 40, 12) === 12);
check('outside the view no scrolling', edgeScrollStep(-5, 300, 40, 12) === 0 &&
    edgeScrollStep(305, 300, 40, 12) === 0);
check('short views keep a middle', edgeScrollStep(30, 60, 40, 12) === 0);
check('no view', edgeScrollStep(10, 0, 40, 12) === 0);

const RELEASE = 7, KEY = 3;
check('release drops', isDropEnd(RELEASE, [RELEASE]));
check('Escape cancels', !isDropEnd(KEY, [RELEASE]));
check('unknown ending cancels', !isDropEnd(null, [RELEASE]) && !isDropEnd(undefined, [RELEASE]));

// --- Cleaning up an interaction ---------------------------------------------

{
    const order = [];
    const cleanup = new Cleanup();
    cleanup.add('monitor', () => order.push('monitor'));
    cleanup.add('timer', () => {
        throw new Error('gone');
    });
    cleanup.add('panel', () => order.push('panel'));
    const errors = [];
    const failed = cleanup.run((name, e) => errors.push(`${name}:${e.message}`));
    check('every step runs, newest first, despite a failing one',
        same(order, ['panel', 'monitor']) && same(failed, ['timer']) && same(errors, ['timer:gone']));
    check('running again does nothing', same(cleanup.run(), []) && order.length === 2 &&
        cleanup.pending === 0);
    cleanup.add('later', () => order.push('later'));
    cleanup.run();
    check('steps added later run once', same(order, ['panel', 'monitor', 'later']) &&
        same(cleanup.run(), []));
    const nested = new Cleanup();
    nested.add('outer', () => nested.run());
    nested.add('inner', () => order.push('inner'));
    nested.run();
    check('a step running the cleanup again does not repeat steps',
        order.filter(o => o === 'inner').length === 1);
}

if (failures) {
    printerr(`${failures} failed`);
    System.exit(1);
}
