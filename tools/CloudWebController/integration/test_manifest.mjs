// Validate the client extension without changing the standard PI V2 documents.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {parse} from "jsonc-parser";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const read = (name) => {
    const errors = [];
    const result = parse(fs.readFileSync(path.join(root, name), "utf8"), errors);
    assert.deepEqual(errors, [], `Invalid JSONC: ${name}`);
    return result;
};
const project = read("assets/interface.json");
const extension = read("assets/mxu-cloudweb.json");
const standardTypes = new Set([
    "Adb",
    "Win32",
    "MacOS",
    "PlayCover",
    "Gamepad",
    "Linux",
]);
assert.ok(project.controller.every((item) => standardTypes.has(item.type)));
assert.ok(!project.controller.some((item) => item.name === "CloudWeb"));
assert.equal(extension.schema_version, 1);
assert.deepEqual(extension.controller, {name: "CloudWeb", label: "$controller.CloudWeb.label"});
assert.equal(new Set(extension.compatible_tasks).size, extension.compatible_tasks.length);
const tasks = new Map();
const options = new Map();
for (const name of project.import ?? []) {
    const item = read(`assets/${name}`);
    for (const task of item.task ?? []) tasks.set(task.name, task);
    for (const [
        key,
        value,
    ] of Object.entries(item.option ?? {}))
        options.set(key, value);
}
for (const name of extension.compatible_tasks) {
    const task = tasks.get(name);
    assert.ok(task, `Unknown task ${name}`);
    assert.ok(task.controller?.includes("Win32-Front"), `No desktop path for ${name}`);
    assert.ok(task.controller?.includes("Linux-Gamescope"), `OS-specific task ${name}`);
    assert.ok(!task.controller.includes("CloudWeb"), `Client extension leaked into PI task ${name}`);
}
for (const name of extension.compatible_options) {
    const option = options.get(name);
    assert.ok(option?.controller?.includes("Win32-Front"));
    assert.ok(option.controller.includes("Linux-Gamescope"));
    assert.ok(!option.controller.includes("CloudWeb"));
}
for (const locale of [
    "zh_cn",
    "zh_tw",
    "en_us",
    "ja_jp",
    "ko_kr",
]) {
    assert.ok(read(`assets/locales/interface/${locale}.json`)["controller.CloudWeb.label"]);
}
console.log(
    `PI controller types unchanged; ${extension.compatible_tasks.length} explicit desktop task references and five locales valid`,
);
