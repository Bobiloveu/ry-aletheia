# Bloub animation engine

This directory vendors the framework-free animation engine from
[`jeremy-prt/bloub`](https://github.com/jeremy-prt/bloub), pinned to
`b4bb3c1b5f93c7b87a2e8d620f667c4093d97749`.

`engine.js` is an unminified, browser-targeted ESM bundle of upstream
`src/bot/engine.ts` and its `src/bot` dependencies. It is kept local so the
vehicle status display never needs a network request or a Vue runtime.

Project-owned code in `../../vehicle_execution_avatar.js` maps Aletheia
vehicle phases to the upstream state IDs and renders the engine frame into the
status page SVG. Keep vehicle meaning out of this vendor directory. When
upgrading, fetch the indicated upstream revision, rebuild this module, update
the revision above, and preserve the accompanying MIT license.

The upstream project is an independent open-source project. This integration
does not imply affiliation with its author or with any third-party product.
