// Rebind Unity's main Metal display to the Flutter-owned UIWindow.
//
// UnityFramework deliberately exposes UnityAppController but keeps
// DisplayConnection private.  Calling this stable, generated selector through
// the Objective-C runtime is safer than treating a reparented UnityView as a
// self-contained Metal view: the latter leaves Unity presenting into the
// bootstrap UIWindow it created during runEmbedded().
#import <Foundation/Foundation.h>
#import <UIKit/UIKit.h>
#import <objc/message.h>

#import "AletheiaVisualizationBridge.h"

void av_unity_rebind_surface(void *unity_controller,
                             void *unity_view,
                             void *host_window) {
  @autoreleasepool {
    id controller = (__bridge id)unity_controller;
    UIView *view = (__bridge UIView *)unity_view;
    UIWindow *window = (__bridge UIWindow *)host_window;
    if (controller == nil || view == nil || window == nil) return;

    SEL main_display = NSSelectorFromString(@"mainDisplay");
    SEL bind_surface = NSSelectorFromString(@"createWithWindow:andView:");
    SEL request_resolution = NSSelectorFromString(@"requestRenderingResolution:");
    SEL recreate_surface = NSSelectorFromString(@"recreateRenderingSurface");
    if (![controller respondsToSelector:main_display] ||
        ![view respondsToSelector:recreate_surface]) {
      NSLog(@"[UnityVizNative] Unity display bridge selectors unavailable");
      return;
    }

    id display = ((id (*)(id, SEL))objc_msgSend)(controller, main_display);
    if (display == nil || ![display respondsToSelector:bind_surface]) {
      NSLog(@"[UnityVizNative] Unity main display unavailable for rebind");
      return;
    }

    ((void (*)(id, SEL, UIWindow *, UIView *))objc_msgSend)(
        display, bind_surface, window, view);

    // The generated UaaL controller obtains its first rendering size from its
    // own full-screen bootstrap window.  A Flutter platform view is smaller
    // and frequently a different aspect ratio.  Keep the drawable resolution
    // in the same coordinate space as the embedded UIView; otherwise Metal
    // presents a full-screen frame which Flutter clips to a horizontal/vertical
    // slice (the exact device-only failure this bridge exists to avoid).
    if ([display respondsToSelector:request_resolution]) {
      const CGFloat scale = view.contentScaleFactor > 0.0
          ? view.contentScaleFactor
          : window.screen.scale;
      const CGSize resolution = CGSizeMake(
          MAX(1.0, round(view.bounds.size.width * scale)),
          MAX(1.0, round(view.bounds.size.height * scale)));
      ((void (*)(id, SEL, CGSize))objc_msgSend)(
          display, request_resolution, resolution);
    }
    [view setNeedsLayout];
    [view layoutIfNeeded];
    ((void (*)(id, SEL))objc_msgSend)(view, recreate_surface);
    NSLog(@"[UnityVizNative] Unity Metal surface rebound to Flutter window: %.0fx%.0f",
          view.bounds.size.width, view.bounds.size.height);
  }
}
