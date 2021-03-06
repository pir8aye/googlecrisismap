// Copyright 2013 Google Inc.  All Rights Reserved.
//
// Licensed under the Apache License, Version 2.0 (the "License"); you may not
// use this file except in compliance with the License.  You may obtain a copy
// of the License at: http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software distrib-
// uted under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
// OR CONDITIONS OF ANY KIND, either express or implied.  See the License for
// specific language governing permissions and limitations under the License.

goog.require('cm.ToolbarView');
goog.require('cm.css');

// TODO(rew): These class names should all be replaced with CrisisMap-specific
// ones, but right now we are using the normal goog.ui.TabBar, so we look
// for those classes
TAB_BAR_CLASS = 'goog-tab-bar';
TAB_CLASS = 'goog-tab';
DISABLED_TAB_CLASS = 'goog-tab-disabled';

function TabViewTest() {
  cm.TestBase.call(this);
  this.mapModel_ = cm.MapModel.newFromMapRoot({});
  this.config_ = undefined;
}
TabViewTest.prototype = new cm.TestBase();
registerTestSuite(TabViewTest);

/**
 * Simple mock for TabItem to use for testing.
 * @implements cm.TabItem
 * @constructor
 */
TabViewTest.TestTabItem = function(title, content) {
  this.title = title;
  this.content = content;
  this.tabView = null;
  this.isSelected = false;
  this.isEnabled = true;
};

/** Class used on the <div>s for the content of mock tabs. */
TabViewTest.TestTabItem.TEST_CLASS = 'MockTabClass';

TabViewTest.TestTabItem.newFromTitle = function(title) {
  return new TabViewTest.TestTabItem(title, cm.ui.create(
      'div', {'class': TabViewTest.TestTabItem.TEST_CLASS},
      'This is the ' + title + 'tab!'));
};

TabViewTest.TestTabItem.prototype.getTitle = function() { return this.title; };

TabViewTest.TestTabItem.prototype.getIcon = function() { return null; };

TabViewTest.TestTabItem.prototype.getContent = function() {
  return this.content;
};

TabViewTest.TestTabItem.prototype.getIsEnabled = function() {
  return this.isEnabled;
};

TabViewTest.TestTabItem.prototype.setSelected = function(isSelected) {
  this.isSelected = isSelected;
};

TabViewTest.TestTabItem.prototype.setTabView = function(tabView) {
  this.tabView = tabView;
};

TabViewTest.TestTabItem.prototype.setTitle = function(newTitle) {
  this.title = newTitle;
  this.tabView.updateTabItem(this);
};

TabViewTest.TestTabItem.prototype.contentString = function() {
  return this.content.toString();
};

TabViewTest.TestTabItem.prototype.setIsEnabled = function(isEnabled) {
  this.isEnabled = isEnabled;
  this.tabView.updateTabItem(this);
};

TabViewTest.TestTabItem.prototype.analyticsSelectionEvent = function() {
  return cm.Analytics.TabPanelAction.NEW_TAB_SELECTED;
};

TabViewTest.prototype.initializeTabView_ = function(opt_numTabs) {
  this.parent_ = new FakeElement('div');
  this.tabView_ = new cm.TabView(this.mapModel_, this.config_);
  // Holds the list of TestTabItems that have been added to the tabView; its
  // ordering matches the order of tabs in the tabView.
  this.tabs_ = [];

  if (opt_numTabs === undefined) opt_numTabs = 3;
  for (var i = 0; i < opt_numTabs; i++) {
    var newTab = TabViewTest.TestTabItem.newFromTitle('Mock ' + i);
    this.tabView_.appendTabItem(newTab);
    this.tabs_.push(newTab);
  }
  this.tabView_.render(this.parent_);

  this.tabBarElem_ = expectDescendantOf(this.parent_, withClass(TAB_BAR_CLASS));
};

TabViewTest.prototype.testCreation = function() {
  this.initializeTabView_();
  expectDescendantOf(
      this.parent_, withClass(TabViewTest.TestTabItem.TEST_CLASS));
  expectEq(3, allDescendantsOf(this.tabBarElem_, withClass(TAB_CLASS)).length);
};

TabViewTest.prototype.testCreation_editingEnabled = function() {
  // Create a fake constructor and provide it instead of the real one.
  var fakeToolbarCtor = function(el) {
    cm.ui.append(el, 'fake toolbar');
  };
  goog.module.Loader.provide('edit', 'cm.ToolbarView', fakeToolbarCtor);

  this.expectEvent(cm.app, 'resize');
  this.config_ = {'enable_editing': true};
  this.initializeTabView_();

  var childNodes = this.parent_.childNodes;
  expectThat(childNodes[0],
      isElement(goog.dom.TagName.DIV, withClass(cm.css.TAB_BAR_CONTAINER)));
  expectThat(childNodes[1],
      isElement(goog.dom.TagName.DIV, withText('fake toolbar')));
  expectThat(childNodes[2],
      isElement(goog.dom.TagName.DIV, withClass(cm.css.TAB_CONTENT)));
};

TabViewTest.prototype.testAppendTabItem = function() {
  this.initializeTabView_();
  this.tabView_.appendTabItem(
      TabViewTest.TestTabItem.newFromTitle('Appended Tab'));
  var tabs = allDescendantsOf(this.tabBarElem_, withClass(TAB_CLASS));
  expectEq(4, tabs.length);
  expectThat(tabs[3], withText(hasSubstr('Appended Tab')));
};

TabViewTest.prototype.testInsertTabItem = function() {
  this.initializeTabView_();
  this.tabView_.insertTabItem(
      TabViewTest.TestTabItem.newFromTitle('testInsertTabItem'), 1);
  var tabs = allDescendantsOf(this.parent_, withClass(TAB_CLASS));
  expectEq(4, tabs.length);
  expectThat(tabs[1], withText(hasSubstr('testInsertTabItem')));
};

TabViewTest.prototype.testTitleChangeHandled = function() {
  this.initializeTabView_();
  for (var i = 0; i < this.tabs_.length; i++) {
    var tab = this.tabs_[i];
    tab.setTitle('testTitleChangeHandled');
    expectThat(allDescendantsOf(this.parent_, withClass(TAB_CLASS))[i],
               withText(hasSubstr('testTitleChangeHandled')));
  }
};

TabViewTest.prototype.testInitialSelection = function() {
  this.initializeTabView_();
  for (var i = 0; i < this.tabs_.length; i++) {
    var tab = this.tabs_[i];
    if (tab === this.tabView_.selectedTabItem()) {
      expectTrue(tab.isSelected);
    } else {
      expectFalse(tab.isSelected);
    }
  }
};

TabViewTest.prototype.chooseRandomTabItem_ = function() {
  return this.tabs_[Math.floor(Math.random() * this.tabs_.length)];
};

TabViewTest.prototype.chooseUnselectedTabItem_ = function() {
  var tab = this.chooseRandomTabItem_();
  while (tab.isSelected) {
    tab = this.chooseRandomTabItem_();
  }
  return tab;
};

TabViewTest.prototype.testSelectTabItem = function() {
  this.initializeTabView_();
  var oldSelected = this.tabView_.selectedTabItem();
  var newSelected = this.chooseUnselectedTabItem_();
  this.tabView_.selectTabItem(newSelected);
  expectFalse(oldSelected.isSelected);
  expectTrue(newSelected.isSelected);
};

TabViewTest.prototype.testRemoveTabItem = function() {
  this.initializeTabView_();
  var tab = this.chooseUnselectedTabItem_();
  this.tabView_.removeTabItem(tab);
  expectEq(null, tab.tabView);
  expectThat(this.parent_, withText(not(hasSubstr(tab.getTitle()))));
};

TabViewTest.prototype.testRemoveSelectedTabItem = function() {
  this.initializeTabView_();
  var tab = this.chooseRandomTabItem_();
  this.tabView_.selectTabItem(tab);
  this.tabView_.removeTabItem(tab);
  expectEq(null, tab.tabView);
  expectThat(this.parent_, withText(not(hasSubstr(tab.getTitle()))));
  // Verifies that a new tab was selected
  expectTrue(this.tabView_.selectedTabItem());
};

TabViewTest.prototype.testSetTabEnabled = function() {
  this.initializeTabView_();
  var tab = this.tabView_.selectedTabItem();
  var tabIndex = goog.array.indexOf(this.tabs_, tab);
  tab.setIsEnabled(false);
  expectThat(allDescendantsOf(this.tabBarElem_, withClass(TAB_CLASS))[tabIndex],
             withClass(DISABLED_TAB_CLASS));
  expectTrue(this.tabView_.selectedTabItem());
  expectNe(tab, this.tabView_.selectedTabItem());
  tab.setIsEnabled(true);
  expectNoDescendantOf(this.tabBarElem_, withClass(DISABLED_TAB_CLASS));
};

TabViewTest.prototype.testSelectedTabItem = function() {
  this.initializeTabView_();
  var tab = this.chooseRandomTabItem_();
  this.tabView_.selectTabItem(tab);
  expectEq(tab, this.tabView_.selectedTabItem());
};

TabViewTest.prototype.testGetTabItemByTitle = function() {
  this.initializeTabView_();
  var tab = this.tabView_.getTabItemByTitle('Mock 0');
  expectEq('Mock 0', tab.getTitle());
  expectEq(null, this.tabView_.getTabItemByTitle('Nonexistent'));
};

TabViewTest.prototype.testSelectASelectedTabItem = function() {
  this.initializeTabView_(2);
  // Make sure that the first tab in the TabView is selected.
  this.tabView_.selectTabItem(0);

  // Listen for and record emitted events from the TabView, so that we
  // can check for expected behavior based on events we send it.
  var tabSelectionChangedEmitted = false;
  cm.events.listen(this.tabView_, cm.events.NEW_TAB_SELECTED,
                   function() { tabSelectionChangedEmitted = true; });
  var selectedTabClickedEmitted = false;
  cm.events.listen(this.tabView_, cm.events.SAME_TAB_SELECTED,
                   function() { selectedTabClickedEmitted = true; });

  // Emit an event from the TabBar, with it thinking that tab 0 has been
  // clicked on.  TabView should recognize this as a click on an already
  // selected tab.
  cm.events.emit(this.tabView_.tabBar_, cm.TabBar.TAB_SELECTED);
  expectTrue(selectedTabClickedEmitted);
  expectFalse(tabSelectionChangedEmitted);
};

TabViewTest.prototype.testSelectAnUnselectedTabItem = function() {
  this.initializeTabView_(2);
  // Make sure that the first tab in the TabView is selected.
  this.tabView_.selectTabItem(0);

  // Listen for and record emitted events from the TabView, so that we
  // can check for expected behavior based on events we send it.
  var tabSelectionChangedEmitted = false;
  cm.events.listen(this.tabView_, cm.events.NEW_TAB_SELECTED,
                   function() { tabSelectionChangedEmitted = true; });
  var selectedTabClickedEmitted = false;
  cm.events.listen(this.tabView_, cm.events.SAME_TAB_SELECTED,
                   function() { selectedTabClickedEmitted = true; });
  this.expectLogAction(cm.Analytics.TabPanelAction.NEW_TAB_SELECTED, null);
  this.expectLogTime(cm.Analytics.TimingCategory.PANEL_ACTION,
                     cm.Analytics.TimingVariable.PANEL_TAB_CHANGED, 1, 1,
                     'Mock 1');

  var clock = this.getMockClock();
  cm.Analytics.startTimer(cm.Analytics.Timer.PANEL_TAB_SELECTED);
  clock.tick();

  // Emit an event from the TabBar, with it thinking that tab 1 (an
  // unselected tab) has been clicked on.
  this.tabView_.tabBar_.selectTab(1);
  cm.events.emit(this.tabView_.tabBar_, cm.TabBar.TAB_SELECTED);
  expectTrue(tabSelectionChangedEmitted);
  expectFalse(selectedTabClickedEmitted);
};

TabViewTest.prototype.testSetExpanded = function() {
  this.initializeTabView_(2);
  // Make sure that the second tab in the TabView is selected.
  var selectedTabIndex = 1;
  this.tabView_.selectTabItem(this.tabs_[selectedTabIndex]);
  var selectedTab = this.tabView_.selectedTabItem();

  this.tabView_.setExpanded(false);
  // Verify that the bar has no selected items, but that tab view still
  // remembers which tab is supposed to be selected
  expectEq(cm.TabView.NO_SELECTION, this.tabView_.tabBar_.getSelectedTab());
  expectEq(selectedTab, this.tabView_.selectedTabItem());

  this.tabView_.setExpanded(true);
  // Verify that the bar has the right item selected and that tab view has
  // a correct selectedTabItem
  expectEq(selectedTabIndex, this.tabView_.tabBar_.getSelectedTab());
  expectEq(selectedTab, this.tabView_.selectedTabItem());
};
