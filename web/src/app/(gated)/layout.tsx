// Same authenticated shell as (app), but without its loading.tsx: a Suspense boundary there would start
// streaming with 200 before the page runs, so forbidden() could no longer answer 403.
export { default } from "../(app)/layout";
