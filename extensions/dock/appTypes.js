// SPDX-License-Identifier: GPL-3.0-or-later
//
// Whether a dock application opens dropped files (fileDrop.js): the content
// types of the files, read by GIO in its threads, against the MimeType list
// of the application's desktop entry, including the types those are a kind
// of (shared-mime-info) and types the user associated with the application
// ("Open With" in Files). Nothing here changes any association. The rules
// are in dropLogic.js appVerdict().

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {gettext as _, ngettext} from 'resource:///org/gnome/shell/extensions/extension.js';

import {appAccepts, appVerdict, isFileUri, schemeType} from './dropLogic.js';

// The content type of uri: what GIO finds (content sniffing included, in
// a thread), the scheme handler type for links, or false when the file
// cannot be read (it went away, its drive was removed).
export function readType(uri, cancellable) {
    if (!isFileUri(uri, Gio.Vfs.get_default().get_supported_uri_schemes()))
        return Promise.resolve(schemeType(uri) ?? false);
    const file = Gio.File.new_for_uri(uri);
    return new Promise(resolve => {
        file.query_info_async('standard::content-type', Gio.FileQueryInfoFlags.NONE,
            GLib.PRIORITY_DEFAULT, cancellable, (_f, res) => {
                try {
                    resolve(file.query_info_finish(res).get_content_type() ?? false);
                } catch {
                    resolve(false);
                }
            });
    });
}

// What app (a Shell.App) makes of uris whose types are known so far (one
// per URI: a type, null while being read, false when unreadable).
export function verdictFor(app, uris, types) {
    const info = app?.get_app_info();
    if (!info)
        return {status: 'no-files'};
    const accepts = appAccepts({
        supportsUris: info.supports_uris(),
        supportsFiles: info.supports_files(),
    }, uris.map(uri => ({uri, hasPath: uri.startsWith('file:')})));
    const id = info.get_id();
    return appVerdict({
        accepts,
        declared: info.get_supported_types() ?? [],
        associated: type => Gio.AppInfo.get_all_for_type(type).some(a => a.get_id() === id),
    }, types, (a, b) => Gio.content_type_is_a(a, b));
}

// The text telling what dropping on the application named name does.
export function verdictText(verdict, name) {
    switch (verdict.status) {
    case 'ok':
    case 'pending':
        return _('Open with %s').replace('%s', name);
    case 'no-files':
        return _('%s cannot open files').replace('%s', name);
    case 'unknown':
        return _('Cannot confirm that %s opens these files').replace('%s', name);
    case 'missing':
        return ngettext('%d of the files is no longer available',
            '%d of the files are no longer available', verdict.count)
            .replace('%d', verdict.count);
    default:
        if (verdict.total === 1)
            return _('%s does not open this type of file').replace('%s', name);
        return ngettext('%s does not open %d of these files', '%s does not open %d of these files',
            verdict.count).replace('%s', name).replace('%d', verdict.count);
    }
}
