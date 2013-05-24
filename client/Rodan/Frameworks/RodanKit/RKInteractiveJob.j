/**
 * This is a general interactive job view that most (if not all) interactive jobs can use.
 */
@implementation RKInteractiveJob : CPWebView
{
}


- (id)initWithFrame:(CGRect)aFrame runJobUUID:(int)aRunJobUUID
{
    console.log("RKInteractiveJob init with frame; RunJob UUID is " + aRunJobUUID);
    var self = [super initWithFrame:aFrame];
    if (self)
    {
        [self setFrameLoadDelegate:self];
        [self setMainFrameURL:@"/interactive/crop?rj_uuid=" + aRunJobUUID];
    }
    return self;
}


- (void)webView:(CPWebView)aWebView didFinishLoadForFrame:(id)aFrame
{
    var bounds = [self bounds],
        domWin = [self DOMWindow];
    console.log("Did finish loading delegate");
}
@end


/**
 * The containing window for the interactive job view.
 */
@implementation RKInteractiveJobWindow : CPWindow
{
    RKInteractiveJob      interactiveJob;
}


- (id)initWithContentRect:(CGRect)aRect styleMask:(int)aMask runJobUUID:(int)aRunJobUUID
{
    var self = [super initWithContentRect:aRect styleMask:aMask];
    if (self)
    {
        interactiveJob = [[RKInteractiveJob alloc] initWithFrame:[[self contentView] bounds] runJobUUID:aRunJobUUID];
        [interactiveJob setAutoresizingMask:CPViewWidthSizable | CPViewHeightSizable];
        [[self contentView] addSubview:interactiveJob];
    }
    return self;
}
@end
