/*!
 * Copyright (c) 2008-2020 Martin Wendt, https://wwWendt.de/
 *
 * Permission is hereby granted, free of charge, to any person obtaining
 * a copy of this software and associated documentation files (the "Software"),
 * to deal in the Software without restriction, including without limitation
 * the rights to use, copy, modify, merge, publish, distribute, sublicense,
 * and/or sell copies of the Software, and to permit persons to whom the
 * Software is furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included
 * in all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
 * EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
 * MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
 * IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
 * DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
 * OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
 * USE OR OTHER DEALINGS IN THE SOFTWARE.
 */

define(["api/SplunkVisualizationUtils","api/SplunkVisualizationBase","splunkjs/mvc"], function(__WEBPACK_EXTERNAL_MODULE_2__, __WEBPACK_EXTERNAL_MODULE_4__, __WEBPACK_EXTERNAL_MODULE_5__) { return /******/ (function(modules) { // webpackBootstrap
/******/ 	// The module cache
/******/ 	var installedModules = {};

/******/ 	// The require function
/******/ 	function __webpack_require__(moduleId) {

/******/ 		// Check if module is in cache
/******/ 		if(installedModules[moduleId])
/******/ 			return installedModules[moduleId].exports;

/******/ 		// Create a new module (and put it into the cache)
/******/ 		var module = installedModules[moduleId] = {
/******/ 			exports: {},
/******/ 			id: moduleId,
/******/ 			loaded: false
/******/ 		};

/******/ 		// Execute the module function
/******/ 		modules[moduleId].call(module.exports, module, module.exports, __webpack_require__);

/******/ 		// Flag the module as loaded
/******/ 		module.loaded = true;

/******/ 		// Return the exports of the module
/******/ 		return module.exports;
/******/ 	}


/******/ 	// expose the modules object (__webpack_modules__)
/******/ 	__webpack_require__.m = modules;

/******/ 	// expose the module cache
/******/ 	__webpack_require__.c = installedModules;

/******/ 	// __webpack_public_path__
/******/ 	__webpack_require__.p = "";

/******/ 	// Load entry module and return exports
/******/ 	return __webpack_require__(0);
/******/ })
/************************************************************************/
/******/ ([
/* 0 */
/***/ (function(module, exports, __webpack_require__) {

	var __WEBPACK_AMD_DEFINE_ARRAY__, __WEBPACK_AMD_DEFINE_RESULT__;"use strict";

	/*
	 * Visualization source
	 */
	!(__WEBPACK_AMD_DEFINE_ARRAY__ = [__webpack_require__(3), __webpack_require__(6), __webpack_require__(4), __webpack_require__(2), __webpack_require__(5), __webpack_require__(1), __webpack_require__(7), __webpack_require__(9) // Add required assets to this list
	], __WEBPACK_AMD_DEFINE_RESULT__ = function ($, _, SplunkVisualizationBase, vizUtils, mvc, treeviewViz, fancytree) {
	  // Extend from SplunkVisualizationBase
	  return SplunkVisualizationBase.extend({
	    initialize: function initialize() {
	      SplunkVisualizationBase.prototype.initialize.apply(this, arguments);
	      this.$el = $(this.el); 
	      // Initialization logic goes here
		  this.chunk = 50000;
		  this.offset = 0;
		  this.database = [];
		  this.database_fields = [];
		  this.isDataLoaded = false;
	    },
	    // Optionally implement to format data returned from search. 
	    // The returned object will be passed to updateView as 'data'
	    formatData: function formatData(data) {
	      if (data.fields.length < 1 && typeof data.meta !== "undefined" && data.meta.done === true && this.database.length==0) {
	        throw new SplunkVisualizationBase.VisualizationError("Missing values. Please include the following fields in your search query: <field 1: label>, <fields 1: value>, optionally:  color, type. E.g. ...| table label, value, color, type");
	      }

	      return data;
	    },
	    // Implement updateView to render a visualization.
	    //  'data' will be the data object returned from formatData or from the search
	    //  'config' will be the configuration property object
	    updateView: function updateView(data, config) {
		
		var error_too_much_data = false;
		
		// 1) No data at all, and our database is empty: return
		if (!data && this.database.length ==0 ) {
			return this;
		
		// 2) Data is coming in, and our database is not yet full (250K Max): Keep pulling data, return
		} else if(!this.isDataLoaded && data.rows && data.rows.length>0 && this.database.length<250000){
			//console.log("Updating View. Database length: " + this.database.length + ". Data length: " + data.rows.length + ".");

			
			this.database = this.database.concat(data.rows);
		    this.database_fields = data.fields;
			
			//console.log("Total Rows in Database: " + this.database.length);
			this.offset += this.chunk;
			
			if(data.rows.length == this.chunk){
				//console.log("Fetching Rows: " + this.offset + " to " + (this.offset + this.chunk));
				this.updateDataParams({count: this.chunk, offset: this.offset});
				return this;
			}
		}
			
			//console.log("Finished fetching data. Total: " + this.database.length);
			if(!this.isDataLoaded) {
				this.database = {"fields":this.database_fields, "rows": this.database}
				this.isDataLoaded = true;
			}
			
			
		
	      this.$el.empty(); // Now load the visualisation

	      var _require = __webpack_require__(1),
	          TreeviewItem = _require.TreeviewItem,
	          TreeviewViz = _require.TreeviewViz;

	      var oViz = new TreeviewViz();
	      oViz.oMVC = mvc;
	      oViz.setConfig(config, this.getPropertyNamespaceInfo().propertyNamespace);
	      oViz.setData(this.database);
	      this.$el.html(oViz.getHTML());
		  if(this.database.rows.length >=250000){
			$("div#" + oViz.id ).append('<span class="tv_error">Warning: This visualization renders up to 250,000 data points. Results might be truncated.</span>');	
		 }
		  
		  
	      $("#" + oViz.id).fancytree(oViz.getFancytreeConfig()); // Show or Hide Connectors
	      $("#" + oViz.id + " .fancytree-container").toggleClass("fancytree-connectors", oViz.showConnectors); // Set font size
	      $("#" + oViz.id + " .fancytree-container").css("font-size", oViz.fontSize + "pt"); // Sort 
		  
		  var initialState = vizUtils.escapeHtml(config[this.getPropertyNamespaceInfo().propertyNamespace + "initialState"]).toLowerCase() || "closed";
	 	  if(initialState=="opened" || initialState=="open") { $.ui.fancytree.getTree("#" + oViz.id).expandAll();}
	    

	      $.ui.fancytree.getTree(oViz.id).rootNode.sortChildren(oViz.get_sort_method(), true); // Set the Token object

	      $.ui.fancytree.getTree(oViz.id).oMVC = mvc;
		  $.ui.fancytree.getTree(oViz.id).oSVB = this;
	      $.ui.fancytree.getTree(oViz.id).tokens = {
	        "tokenLabel": oViz.tokenLabel,
	        "tokenId": oViz.tokenId,
	        "tokenParentId": oViz.tokenParentId,
	        "tokenValuePrefix": oViz.tokenValuePrefix,
	        "tokenValueSuffix": oViz.tokenValueSuffix,
	        "tokenPrefix": oViz.tokenPrefix,
	        "tokenSuffix": oViz.tokenSuffix,
	        "tokenDelimiter": oViz.tokenDelimiter,
			"isDrillDownConfigured": oViz.isDrillDownConfigured
	      };
		  
	    },
	    // Search data params
	    getInitialDataParams: function getInitialDataParams() {
	      return {
	        outputMode: SplunkVisualizationBase.ROW_MAJOR_OUTPUT_MODE,
	        count: 50000
	      };
	    }
	  });
	}.apply(exports, __WEBPACK_AMD_DEFINE_ARRAY__), __WEBPACK_AMD_DEFINE_RESULT__ !== undefined && (module.exports = __WEBPACK_AMD_DEFINE_RESULT__));

/***/ }),
/* 1 */
/***/ (function(module, exports, __webpack_require__) {

	
		// ----------------------------------------------------------------------------------------------------------- TreeviewItem ----------------------------------------------------------------------------------------------------------- 

		class TreeviewItem {
			constructor(id,label, tooltip){
				this.id = id;
				this.parentId = 0;
				this.label = label || "" ;
				this.tooltip = tooltip || "";
				this.childIds = [];
				this.hasChildren = false;
				this.color = null;
				this.extraData = {};
				// Custom Skin Default Icons - seems to be a bug where open icon doesn't show, so only using iconFolder for now:
				this.iconFolder = "folder";
				this.iconDoc = "file";
			}
		
			addChildId(childId){
				this.childIds.push(childId);
				this.hasChildren=true;
			}
			
			removeChildId(childId){
				var popChildId = function(value) { return value!=childId};
				this.childIds = this.childIds.filter(popChildId);
				if(this.childIds.length==0){
					this.hasChildren=false;
				}
			}
			
			/* 
				does this node have a specific ID in its children, or children's children?
			*/
			hasChildId(itemId){
				return (typeof this.childIds[itemId] != 'undefined')
			}
			
			
		}
		
		
		
		// ----------------------------------------------------------------------------------------------------------- TreeviewViz ----------------------------------------------------------------------------------------------------------- 
		/*
			Contains everything for the Treeview Viz
		*/
		class TreeviewViz{
			constructor(){
				this.id = this._createID();
				this.items = {};
				this.root = new TreeviewItem(this.id , "_root", "","")
				this.showConnectors = true;
				this.showCheckbox = false;
				this.showFoldersFirst = true;
				this.sortBy = "label";
				this.skin = "win8";
				this.autoCollapse = false;
				this.showIcons = true;
				this.selectMode = "single";
	      this.defaultSelection = false;
				this.accordionMode = false;
				this.accordionModeBgColor = "#efefef";
				this.accordionModeTextColor = "#000000";
				this.accordionMinWidth = 200;
				this.colnames = [];
				this.fontSize = 14;
				
				this.tokenParentId = "tv_parent_id_token";
				this.tokenId = "tv_id_token";
				this.tokenLabel = "tv_label_token";
				this.tokenValuePrefix = "";
				this.tokenValueSuffix = "";
				this.tokenPrefix = "";
				this.tokenSuffix = "";
				this.tokenDelimiter = "";
				
				this.colors = [];
				
				//------ Splunk variables
				this.isSplunkDarkMode = false;
				this.isDrillDownConfigured = false;
				this.showLegend = true;
				this.oMVC;
				this.oSVB;
				
				this.error_too_much_data = false;
				
			}

			
			// Create a unique ID for the CSS selector
			_createID() {
				var s = [];
				var hexDigits = "0123456789abcdef";
				for (var i = 0; i < 10; i+=1) {
					s[i] = hexDigits.substr(Math.floor(Math.random() * 0x10), 1);
				}
				var uuid = s.join("");
				return "tv_" + uuid;
			}
			
			
			
			
			setConfig(config, namespace){
				var vizUtils = __webpack_require__(2);
				var validSortBy={"label":"label","as-is":"as-is","id":"id"};
				var validSkin={"win8":"win8","win8xxl":"win8xxl","lion":"lion","custom":"custom"};
				var validSelectMode={"single":1,"multi":3};
				var validFontSize={10:10,12:12,14:14,16:16,18:18};
				
				// Get Config parameters:
				this.showConnectors = vizUtils.normalizeBoolean(config[namespace + "showConnectors"], true);
				this.showCheckbox = vizUtils.normalizeBoolean(config[namespace + "showCheckbox"], false);
				this.showFoldersFirst = vizUtils.normalizeBoolean(config[namespace + "showFoldersFirst"], true);
				this.sortBy = vizUtils.escapeHtml(config[namespace + "sortBy"]).toLowerCase() || "label";
				this.skin = vizUtils.escapeHtml(config[namespace + "skin"]) || "win8";
				this.autoCollapse = vizUtils.normalizeBoolean(config[namespace + "autoCollapse"], false);
				this.showIcons = vizUtils.normalizeBoolean(config[namespace + "showIcons"], true);
				this.selectMode = vizUtils.escapeHtml(config[namespace + "selectMode"]).toLowerCase() || "single";
				this.defaultSelection = vizUtils.normalizeBoolean(config[namespace + "defaultSelection"], false);
	      this.accordionMode = vizUtils.normalizeBoolean(config[namespace + "accordionMode"], false);
				this.accordionModeBgColor = vizUtils.escapeHtml(config[namespace + "accordionModeBgColor"]).toLowerCase() || "#efefef";
				this.accordionModeTextColor = vizUtils.escapeHtml(config[namespace + "accordionModeTextColor"]).toLowerCase() || "#000000";
				this.accordionMinWidth = parseInt(vizUtils.escapeHtml(config[namespace + "accordionMinWidth"]),10) || "200";
				this.tableMode = vizUtils.normalizeBoolean(config[namespace + "tableMode"], false);
				this.tokenParentId = vizUtils.escapeHtml(config[namespace + "tokenParentId"]).toLowerCase() || "tv_parent_id_token";
				this.tokenLabel = vizUtils.escapeHtml(config[namespace + "tokenLabel"]).toLowerCase() || "tv_label_token";
				this.tokenId = vizUtils.escapeHtml(config[namespace + "tokenId"]).toLowerCase() || "tv_id_token";
				this.fontSize = parseInt(vizUtils.escapeHtml(config[namespace + "fontSize"]),10) || 10;
				this.tokenValuePrefix = vizUtils.escapeHtml(config[namespace + "tokenValuePrefix"]).replace("&quot;","\"") || "";
				this.tokenValueSuffix = vizUtils.escapeHtml(config[namespace + "tokenValueSuffix"]).replace("&quot;","\"") || "";
				this.tokenPrefix = vizUtils.escapeHtml(config[namespace + "tokenPrefix"]).replace("&quot;","\"") || "";
				this.tokenSuffix = vizUtils.escapeHtml(config[namespace + "tokenSuffix"]).replace("&quot;","\"") || "";
				this.tokenDelimiter = vizUtils.escapeHtml(config[namespace + "tokenDelimiter"]).replace("&quot;","\"") || "";

				
				// Validation
				if(! validSortBy[this.sortBy]) { this.sortBy = "label";}
				if(! validSkin[this.skin]) { this.skin = "win8";}
				if(! validSelectMode[this.selectMode]) { this.selectMode = "single";}
				this.selectMode = validSelectMode[this.selectMode];
				if(this.accordionMinWidth <100){ this.accordionMinWidth = 100;}
				if(this.accordionMinWidth >1000){ this.accordionMinWidth = 1000;}
				if(! validFontSize[this.fontSize]) { this.fontSize = 10;}
				if(this.skin=="custom" && this.fontSize>14) { this.fontSize = 14;}
				
				if (typeof vizUtils.getCurrentTheme === "function") { 
					// safe to use the function
					this.isSplunkDarkMode = (vizUtils.getCurrentTheme()=="dark");
				}else{
					//version 6.x, 7.0
					this.isSplunkDarkMode = false;
				}
				
				try {
					this.isDrillDownConfigured = config['display.visualizations.custom.drilldown']!='none';
				}catch(err) {
					this.isDrillDownConfigured = false;
				}
			}
			
			
			
			setData(data){
				var i = 0;
				var j=0;
				var fields = [];
				var data_item;
				var rangeFieldName = "";
				var current_item;
				var vizUtils = __webpack_require__(2);
				var oItem;
				var oParent;
				var extraFieldNames = [];
				var validIcons = {"ad":1,"address-book":1,"address-card":1,"adjust":1,"air-freshener":1,"align-center":1,"align-justify":1,"align-left":1,"align-right":1,"allergies":1,"ambulance":1,"american-sign-language-interpreting":1,"anchor":1,"angle-double-down":1,"angle-double-left":1,"angle-double-right":1,"angle-double-up":1,"angle-down":1,"angle-left":1,"angle-right":1,"angle-up":1,"angry":1,"ankh":1,"archive":1,"archway":1,"arrow-alt-circle-down":1,"arrow-alt-circle-left":1,"arrow-alt-circle-right":1,"arrow-alt-circle-up":1,"arrow-circle-down":1,"arrow-circle-left":1,"arrow-circle-right":1,"arrow-circle-up":1,"arrow-down":1,"arrow-left":1,"arrow-right":1,"arrow-up":1,"arrows-alt":1,"arrows-alt-h":1,"arrows-alt-v":1,"assistive-listening-systems":1,"asterisk":1,"at":1,"atlas":1,"atom":1,"audio-description":1,"award":1,"baby":1,"baby-carriage":1,"backspace":1,"backward":1,"bacon":1,"balance-scale":1,"ban":1,"band-aid":1,"barcode":1,"bars":1,"baseball-ball":1,"basketball-ball":1,"bath":1,"battery-empty":1,"battery-full":1,"battery-half":1,"battery-quarter":1,"battery-three-quarters":1,"bed":1,"beer":1,"bell":1,"bell-slash":1,"bezier-curve":1,"bible":1,"bicycle":1,"binoculars":1,"biohazard":1,"birthday-cake":1,"blender":1,"blender-phone":1,"blind":1,"blog":1,"bold":1,"bolt":1,"bomb":1,"bone":1,"bong":1,"book":1,"book-dead":1,"book-medical":1,"book-open":1,"book-reader":1,"bookmark":1,"bowling-ball":1,"box":1,"box-open":1,"boxes":1,"braille":1,"brain":1,"bread-slice":1,"briefcase":1,"briefcase-medical":1,"broadcast-tower":1,"broom":1,"brush":1,"bug":1,"building":1,"bullhorn":1,"bullseye":1,"burn":1,"bus":1,"bus-alt":1,"business-time":1,"calculator":1,"calendar":1,"calendar-alt":1,"calendar-check":1,"calendar-day":1,"calendar-minus":1,"calendar-plus":1,"calendar-times":1,"calendar-week":1,"camera":1,"camera-retro":1,"campground":1,"candy-cane":1,"cannabis":1,"capsules":1,"car":1,"car-alt":1,"car-battery":1,"car-crash":1,"car-side":1,"caret-down":1,"caret-left":1,"caret-right":1,"caret-square-down":1,"caret-square-left":1,"caret-square-right":1,"caret-square-up":1,"caret-up":1,"carrot":1,"cart-arrow-down":1,"cart-plus":1,"cash-register":1,"cat":1,"certificate":1,"chair":1,"chalkboard":1,"chalkboard-teacher":1,"charging-station":1,"chart-area":1,"chart-bar":1,"chart-line":1,"chart-pie":1,"check":1,"check-circle":1,"check-double":1,"check-square":1,"cheese":1,"chess":1,"chess-bishop":1,"chess-board":1,"chess-king":1,"chess-knight":1,"chess-pawn":1,"chess-queen":1,"chess-rook":1,"chevron-circle-down":1,"chevron-circle-left":1,"chevron-circle-right":1,"chevron-circle-up":1,"chevron-down":1,"chevron-left":1,"chevron-right":1,"chevron-up":1,"child":1,"church":1,"circle":1,"circle-notch":1,"city":1,"clinic-medical":1,"clipboard":1,"clipboard-check":1,"clipboard-list":1,"clock":1,"clone":1,"closed-captioning":1,"cloud":1,"cloud-download-alt":1,"cloud-meatball":1,"cloud-moon":1,"cloud-moon-rain":1,"cloud-rain":1,"cloud-showers-heavy":1,"cloud-sun":1,"cloud-sun-rain":1,"cloud-upload-alt":1,"cocktail":1,"code":1,"code-branch":1,"coffee":1,"cog":1,"cogs":1,"coins":1,"columns":1,"comment":1,"comment-alt":1,"comment-dollar":1,"comment-dots":1,"comment-medical":1,"comment-slash":1,"comments":1,"comments-dollar":1,"compact-disc":1,"compass":1,"compress":1,"compress-arrows-alt":1,"concierge-bell":1,"cookie":1,"cookie-bite":1,"copy":1,"copyright":1,"couch":1,"credit-card":1,"crop":1,"crop-alt":1,"cross":1,"crosshairs":1,"crow":1,"crown":1,"crutch":1,"cube":1,"cubes":1,"cut":1,"database":1,"deaf":1,"democrat":1,"desktop":1,"dharmachakra":1,"diagnoses":1,"dice":1,"dice-d20":1,"dice-d6":1,"dice-five":1,"dice-four":1,"dice-one":1,"dice-six":1,"dice-three":1,"dice-two":1,"digital-tachograph":1,"directions":1,"divide":1,"dizzy":1,"dna":1,"dog":1,"dollar-sign":1,"dolly":1,"dolly-flatbed":1,"donate":1,"door-closed":1,"door-open":1,"dot-circle":1,"dove":1,"download":1,"drafting-compass":1,"dragon":1,"draw-polygon":1,"drum":1,"drum-steelpan":1,"drumstick-bite":1,"dumbbell":1,"dumpster":1,"dumpster-fire":1,"dungeon":1,"edit":1,"egg":1,"eject":1,"ellipsis-h":1,"ellipsis-v":1,"envelope":1,"envelope-open":1,"envelope-open-text":1,"envelope-square":1,"equals":1,"eraser":1,"ethernet":1,"euro-sign":1,"exchange-alt":1,"exclamation":1,"exclamation-circle":1,"exclamation-triangle":1,"expand":1,"expand-arrows-alt":1,"external-link-alt":1,"external-link-square-alt":1,"eye":1,"eye-dropper":1,"eye-slash":1,"fast-backward":1,"fast-forward":1,"fax":1,"feather":1,"feather-alt":1,"female":1,"fighter-jet":1,"file":1,"file-alt":1,"file-archive":1,"file-audio":1,"file-code":1,"file-contract":1,"file-csv":1,"file-download":1,"file-excel":1,"file-export":1,"file-image":1,"file-import":1,"file-invoice":1,"file-invoice-dollar":1,"file-medical":1,"file-medical-alt":1,"file-pdf":1,"file-powerpoint":1,"file-prescription":1,"file-signature":1,"file-upload":1,"file-video":1,"file-word":1,"fill":1,"fill-drip":1,"film":1,"filter":1,"fingerprint":1,"fire":1,"fire-alt":1,"fire-extinguisher":1,"first-aid":1,"fish":1,"fist-raised":1,"flag":1,"flag-checkered":1,"flag-usa":1,"flask":1,"flushed":1,"folder":1,"folder-minus":1,"folder-open":1,"folder-plus":1,"font":1,"football-ball":1,"forward":1,"frog":1,"frown":1,"frown-open":1,"funnel-dollar":1,"futbol":1,"gamepad":1,"gas-pump":1,"gavel":1,"gem":1,"genderless":1,"ghost":1,"gift":1,"gifts":1,"glass-cheers":1,"glass-martini":1,"glass-martini-alt":1,"glass-whiskey":1,"glasses":1,"globe":1,"globe-africa":1,"globe-americas":1,"globe-asia":1,"globe-europe":1,"golf-ball":1,"gopuram":1,"graduation-cap":1,"greater-than":1,"greater-than-equal":1,"grimace":1,"grin":1,"grin-alt":1,"grin-beam":1,"grin-beam-sweat":1,"grin-hearts":1,"grin-squint":1,"grin-squint-tears":1,"grin-stars":1,"grin-tears":1,"grin-tongue":1,"grin-tongue-squint":1,"grin-tongue-wink":1,"grin-wink":1,"grip-horizontal":1,"grip-lines":1,"grip-lines-vertical":1,"grip-vertical":1,"guitar":1,"h-square":1,"hamburger":1,"hammer":1,"hamsa":1,"hand-holding":1,"hand-holding-heart":1,"hand-holding-usd":1,"hand-lizard":1,"hand-middle-finger":1,"hand-paper":1,"hand-peace":1,"hand-point-down":1,"hand-point-left":1,"hand-point-right":1,"hand-point-up":1,"hand-pointer":1,"hand-rock":1,"hand-scissors":1,"hand-spock":1,"hands":1,"hands-helping":1,"handshake":1,"hanukiah":1,"hard-hat":1,"hashtag":1,"hat-wizard":1,"haykal":1,"hdd":1,"heading":1,"headphones":1,"headphones-alt":1,"headset":1,"heart":1,"heart-broken":1,"heartbeat":1,"helicopter":1,"highlighter":1,"hiking":1,"hippo":1,"history":1,"hockey-puck":1,"holly-berry":1,"home":1,"horse":1,"horse-head":1,"hospital":1,"hospital-alt":1,"hospital-symbol":1,"hot-tub":1,"hotdog":1,"hotel":1,"hourglass":1,"hourglass-end":1,"hourglass-half":1,"hourglass-start":1,"house-damage":1,"hryvnia":1,"i-cursor":1,"ice-cream":1,"icicles":1,"id-badge":1,"id-card":1,"id-card-alt":1,"igloo":1,"image":1,"images":1,"inbox":1,"indent":1,"industry":1,"infinity":1,"info":1,"info-circle":1,"italic":1,"jedi":1,"joint":1,"journal-whills":1,"kaaba":1,"key":1,"keyboard":1,"khanda":1,"kiss":1,"kiss-beam":1,"kiss-wink-heart":1,"kiwi-bird":1,"landmark":1,"language":1,"laptop":1,"laptop-code":1,"laptop-medical":1,"laugh":1,"laugh-beam":1,"laugh-squint":1,"laugh-wink":1,"layer-group":1,"leaf":1,"lemon":1,"less-than":1,"less-than-equal":1,"level-down-alt":1,"level-up-alt":1,"life-ring":1,"lightbulb":1,"link":1,"lira-sign":1,"list":1,"list-alt":1,"list-ol":1,"list-ul":1,"location-arrow":1,"lock":1,"lock-open":1,"long-arrow-alt-down":1,"long-arrow-alt-left":1,"long-arrow-alt-right":1,"long-arrow-alt-up":1,"low-vision":1,"luggage-cart":1,"magic":1,"magnet":1,"mail-bulk":1,"male":1,"map":1,"map-marked":1,"map-marked-alt":1,"map-marker":1,"map-marker-alt":1,"map-pin":1,"map-signs":1,"marker":1,"mars":1,"mars-double":1,"mars-stroke":1,"mars-stroke-h":1,"mars-stroke-v":1,"mask":1,"medal":1,"medkit":1,"meh":1,"meh-blank":1,"meh-rolling-eyes":1,"memory":1,"menorah":1,"mercury":1,"meteor":1,"microchip":1,"microphone":1,"microphone-alt":1,"microphone-alt-slash":1,"microphone-slash":1,"microscope":1,"minus":1,"minus-circle":1,"minus-square":1,"mitten":1,"mobile":1,"mobile-alt":1,"money-bill":1,"money-bill-alt":1,"money-bill-wave":1,"money-bill-wave-alt":1,"money-check":1,"money-check-alt":1,"monument":1,"moon":1,"mortar-pestle":1,"mosque":1,"motorcycle":1,"mountain":1,"mouse-pointer":1,"mug-hot":1,"music":1,"network-wired":1,"neuter":1,"newspaper":1,"not-equal":1,"notes-medical":1,"object-group":1,"object-ungroup":1,"oil-can":1,"om":1,"otter":1,"outdent":1,"pager":1,"paint-brush":1,"paint-roller":1,"palette":1,"pallet":1,"paper-plane":1,"paperclip":1,"parachute-box":1,"paragraph":1,"parking":1,"passport":1,"pastafarianism":1,"paste":1,"pause":1,"pause-circle":1,"paw":1,"peace":1,"pen":1,"pen-alt":1,"pen-fancy":1,"pen-nib":1,"pen-square":1,"pencil-alt":1,"pencil-ruler":1,"people-carry":1,"pepper-hot":1,"percent":1,"percentage":1,"person-booth":1,"phone":1,"phone-slash":1,"phone-square":1,"phone-volume":1,"piggy-bank":1,"pills":1,"pizza-slice":1,"place-of-worship":1,"plane":1,"plane-arrival":1,"plane-departure":1,"play":1,"play-circle":1,"plug":1,"plus":1,"plus-circle":1,"plus-square":1,"podcast":1,"poll":1,"poll-h":1,"poo":1,"poo-storm":1,"poop":1,"portrait":1,"pound-sign":1,"power-off":1,"pray":1,"praying-hands":1,"prescription":1,"prescription-bottle":1,"prescription-bottle-alt":1,"print":1,"procedures":1,"project-diagram":1,"puzzle-piece":1,"qrcode":1,"question":1,"question-circle":1,"quidditch":1,"quote-left":1,"quote-right":1,"quran":1,"radiation":1,"radiation-alt":1,"rainbow":1,"random":1,"receipt":1,"recycle":1,"redo":1,"redo-alt":1,"registered":1,"reply":1,"reply-all":1,"republican":1,"restroom":1,"retweet":1,"ribbon":1,"ring":1,"road":1,"robot":1,"rocket":1,"route":1,"rss":1,"rss-square":1,"ruble-sign":1,"ruler":1,"ruler-combined":1,"ruler-horizontal":1,"ruler-vertical":1,"running":1,"rupee-sign":1,"sad-cry":1,"sad-tear":1,"satellite":1,"satellite-dish":1,"save":1,"school":1,"screwdriver":1,"scroll":1,"sd-card":1,"search":1,"search-dollar":1,"search-location":1,"search-minus":1,"search-plus":1,"seedling":1,"server":1,"shapes":1,"share":1,"share-alt":1,"share-alt-square":1,"share-square":1,"shekel-sign":1,"shield-alt":1,"ship":1,"shipping-fast":1,"shoe-prints":1,"shopping-bag":1,"shopping-basket":1,"shopping-cart":1,"shower":1,"shuttle-van":1,"sign":1,"sign-in-alt":1,"sign-language":1,"sign-out-alt":1,"signal":1,"signature":1,"sim-card":1,"sitemap":1,"skating":1,"skiing":1,"skiing-nordic":1,"skull":1,"skull-crossbones":1,"slash":1,"sleigh":1,"sliders-h":1,"smile":1,"smile-beam":1,"smile-wink":1,"smog":1,"smoking":1,"smoking-ban":1,"sms":1,"snowboarding":1,"snowflake":1,"snowman":1,"snowplow":1,"socks":1,"solar-panel":1,"sort":1,"sort-alpha-down":1,"sort-alpha-up":1,"sort-amount-down":1,"sort-amount-up":1,"sort-down":1,"sort-numeric-down":1,"sort-numeric-up":1,"sort-up":1,"spa":1,"space-shuttle":1,"spider":1,"spinner":1,"splotch":1,"spray-can":1,"square":1,"square-full":1,"square-root-alt":1,"stamp":1,"star":1,"star-and-crescent":1,"star-half":1,"star-half-alt":1,"star-of-david":1,"star-of-life":1,"step-backward":1,"step-forward":1,"stethoscope":1,"sticky-note":1,"stop":1,"stop-circle":1,"stopwatch":1,"store":1,"store-alt":1,"stream":1,"street-view":1,"strikethrough":1,"stripe":1,"stroopwafel":1,"subscript":1,"subway":1,"suitcase":1,"suitcase-rolling":1,"sun":1,"superscript":1,"surprise":1,"swatchbook":1,"swimmer":1,"swimming-pool":1,"synagogue":1,"sync":1,"sync-alt":1,"syringe":1,"table":1,"table-tennis":1,"tablet":1,"tablet-alt":1,"tablets":1,"tachometer-alt":1,"tag":1,"tags":1,"tape":1,"tasks":1,"taxi":1,"teeth":1,"teeth-open":1,"temperature-high":1,"temperature-low":1,"tenge":1,"terminal":1,"text-height":1,"text-width":1,"th":1,"th-large":1,"th-list":1,"theater-masks":1,"thermometer":1,"thermometer-empty":1,"thermometer-full":1,"thermometer-half":1,"thermometer-quarter":1,"thermometer-three-quarters":1,"thumbs-down":1,"thumbs-up":1,"thumbtack":1,"ticket-alt":1,"times":1,"times-circle":1,"tint":1,"tint-slash":1,"tired":1,"toggle-off":1,"toggle-on":1,"toilet":1,"toilet-paper":1,"toolbox":1,"tools":1,"tooth":1,"torah":1,"torii-gate":1,"tractor":1,"trademark":1,"traffic-light":1,"train":1,"tram":1,"transgender":1,"transgender-alt":1,"trash":1,"trash-alt":1,"trash-restore":1,"trash-restore-alt":1,"tree":1,"trophy":1,"truck":1,"truck-loading":1,"truck-monster":1,"truck-moving":1,"truck-pickup":1,"tshirt":1,"tty":1,"tv":1,"umbrella":1,"umbrella-beach":1,"underline":1,"undo":1,"undo-alt":1,"universal-access":1,"university":1,"unlink":1,"unlock":1,"unlock-alt":1,"upload":1,"user":1,"user-alt":1,"user-alt-slash":1,"user-astronaut":1,"user-check":1,"user-circle":1,"user-clock":1,"user-cog":1,"user-edit":1,"user-friends":1,"user-graduate":1,"user-injured":1,"user-lock":1,"user-md":1,"user-minus":1,"user-ninja":1,"user-nurse":1,"user-plus":1,"user-secret":1,"user-shield":1,"user-slash":1,"user-tag":1,"user-tie":1,"user-times":1,"users":1,"users-cog":1,"utensil-spoon":1,"utensils":1,"vector-square":1,"venus":1,"venus-double":1,"venus-mars":1,"vial":1,"vials":1,"video":1,"video-slash":1,"vihara":1,"volleyball-ball":1,"volume-down":1,"volume-mute":1,"volume-off":1,"volume-up":1,"vote-yea":1,"vr-cardboard":1,"walking":1,"wallet":1,"warehouse":1,"water":1,"weight":1,"weight-hanging":1,"wheelchair":1,"wifi":1,"wind":1,"window-close":1,"window-maximize":1,"window-minimize":1,"window-restore":1,"wine-bottle":1,"wine-glass":1,"wine-glass-alt":1,"won-sign":1,"wrench":1,"x-ray":1,"yen-sign":1,"yin-yang":1};
				const {  TreeviewItem, TreeviewViz } = __webpack_require__(1);
				try{
					//------------------------------  Get data row field indexes ----------------------------------------------------------------------
					for (i=0; i<data.fields.length; i++){
						fields[data.fields[i].name.toLowerCase()]  = i;
						extraFieldNames[i] = data.fields[i].name.toLowerCase();
					}
					for (i=0; i<data.rows.length; i++){
						data_item = data.rows[i];
						//------------------------------  Create or Locate item Objects ----------------------------------------------------------------------
						oItem = new TreeviewItem();
						oItem.label = (typeof fields["label"] !=='undefined') && (typeof data_item[fields["label"]] !=='undefined') ? vizUtils.escapeHtml(data_item[fields["label"]]) : "";
						oItem.id = (typeof fields["id"] !=='undefined') && (typeof data_item[fields["id"]] !=='undefined') ? vizUtils.escapeHtml(data_item[fields["id"]]) : this.id + "_" + i;
						oItem.parentId = (typeof fields["parentid"] !=='undefined') && (typeof data_item[fields["parentid"]] !=='undefined') ? vizUtils.escapeHtml(data_item[fields["parentid"]]) : this.id + "_root";
						oItem.tooltip = (typeof fields["tooltip"] !=='undefined') && (typeof data_item[fields["tooltip"]] !=='undefined') ? vizUtils.escapeHtml(data_item[fields["tooltip"]]) : "";
						oItem.iconFolder = (typeof fields["iconfolder"] !=='undefined') && (typeof data_item[fields["iconfolder"]] !=='undefined') ? vizUtils.escapeHtml(data_item[fields["iconfolder"]]) : oItem.iconFolder;
						oItem.iconDoc = (typeof fields["icondoc"] !=='undefined') && (typeof data_item[fields["icondoc"]] !=='undefined') ? vizUtils.escapeHtml(data_item[fields["icondoc"]]) : oItem.iconDoc;
						oItem.color = (typeof fields["color"] !=='undefined') && (typeof data_item[fields["color"]] !=='undefined') ? vizUtils.escapeHtml(data_item[fields["color"]]) : null;
						// Validate color is a hex color:
						if(! /\#[a-fA-F0-9]{6,8}/.test(oItem.color)) { oItem.color = null;}
						
						
						if(typeof validIcons[oItem.iconFolder]==='undefined') { oItem.iconFolder="folder";}
						if(typeof validIcons[oItem.iconDoc]==='undefined') { oItem.iconDoc="file";}
						oItem.extraData = {};
						for(j=0;j<extraFieldNames.length;j++){
							oItem.extraData[extraFieldNames[j]] = data_item[j];
						}
						
						//---- Validation
						if(oItem.id.trim()=="") { oItem.id=this.id + "_" + i;}
						if(oItem.id == oItem.parentId || oItem.parentId.trim()=="") { oItem.parentId = this.id + "_root";}
						
						//-- Optional Fields
						if (typeof fields["icon"] !=='undefined')	{ oItem.faIcon	= vizUtils.escapeHtml(data_item[fields["icon"]])		}
						
						// We can only add unique IDs. Once added, you can't add again. This avoids cycles in the tree.
						if(typeof this.items[oItem.id] == 'undefined'){
							//1) Create + add the item
							this.items[oItem.id] = oItem;
						
							//2) Create / Update the Parent
							if(oItem.parentId == this.id + "_root"){
								this.root.addChildId(oItem.id);
							}else{
								oParent = this.getItemById(oItem.parentId);
								oParent.addChildId(oItem.id);
							}
						}else{
							// Already exists - update selected fields only
							if(this.items[oItem.id].label !="") {this.items[oItem.id].label = oItem.label;}
							if(this.items[oItem.id].tooltip !="" ){ this.items[oItem.id].tooltip = oItem.tooltip;}
							if(this.items[oItem.id].iconFolder !="") {this.items[oItem.id].iconFolder = oItem.iconFolder;}
							if(this.items[oItem.id].iconDoc !="") {this.items[oItem.id].iconDoc = oItem.iconDoc;}
							// Check if the parent has changed
								if(this.items[oItem.id].parentId != oItem.parentId){
									// First -remove from current parent:
									if(this.items[oItem.id].parentId == this.id + "_root"){
										this.root.removeChildId( oItem.id );
									}else{
										if(this.items[this.items[oItem.id].parentId]) { this.items[this.items[oItem.id].parentId].removeChildId( oItem.id );}
									}
									// Check we are not assigning to root node:
									
									// Now check to see if the new parent exists:
									if(oItem.parentId == this.id + "_root"){
										newParent = this.root;
									}else{

										if(typeof this.items[oItem.parentId] == 'undefined'){
											var newParent = new TreeviewItem();
											newParent.label = oItem.parentId;
											newParent.id = oItem.parentId;
											this.items[newParent.id] = newParent;
											this.root.addChildId(newParent.id);
										}
									
										newParent = this.items[oItem.parentId];
									}
									
									//Only link if there isn't a cycle
									if(!this.itemHasDecendentId(oItem.id,newParent.id)){
										newParent.addChildId(oItem.id);
									} else{
										this.root.addChildId(oItem.id);
									}
										
								}
							
							
						}
						if(oItem.color) { this.addColorDefiniton(oItem.color); this.items[oItem.id].color = oItem.color;}
					}
				} catch(err) {
					console.log("Error setting data. " + err);
				}
			}
			
			
			
			/* Check to see if a node has a decendant
			*/
			
			itemHasDecendentId(nodeId, decendentId){
				var child;
				var i=0;
				var node;
				var childId;
				//1) Get the node, if id doesn't exist return false;
				if(typeof this.items[nodeId] != "undefined"){
					node = this.items[nodeId];
				}else{
					return false;
				}
				
				//2) Check me
				if(node.id == decendentId){
					return true;
				}
				
				//3) Check if children exist - if not return false
				if(node.hasChildren === false){
					return false;
				}
				
				//4) Get the children, and call itemHasDecendentId on each one
				for(i=0; i<node.childIds.length;i++){
					childId = node.childIds[i];
					if(this.itemHasDecendentId(childId, decendentId)){
						return true;
					}
				}
				
				//4) No children have this decendentID as a child. All good.
				return false;	
				
			}
			
			/* Create a list of custom colours
			*/
			addColorDefiniton(hexCode){
				if(this.colors[hexCode]) {
					return;
				}else{
					this.colors[hexCode] = "custom_color_" + this.id + "_";
				}
			}

			/* Get CSS for custom colors*/
			getCSSForCustomColors(){
				var css = "";
				var i;
				var counter = 0;
				var keys = Object.keys(this.colors);
				for(counter = 0; counter < keys.length; counter++){
					css += "." + this.colors[keys[counter]] + counter + "{color:" + keys[counter] + "; ";
					css += this.convertPicColorInCSS(keys[counter]) + ";} ";
					this.colors[keys[counter]] += counter; 
				}
				return css;
			}
			
			hexToRgb(hex) {
				  // Expand shorthand form (e.g. "03F") to full form (e.g. "0033FF")
				  const shorthandRegex = /^#?([a-f\d])([a-f\d])([a-f\d])$/i;
				  hex = hex.replace(shorthandRegex, (m, r, g, b) => {
					return r + r + g + g + b + b;
				  });

				  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
				  return result
					? [
					  parseInt(result[1], 16),
					  parseInt(result[2], 16),
					  parseInt(result[3], 16),
					]
					: null;
				}

			convertPicColorInCSS(hexCode){
				var rgb = this.hexToRgb(hexCode);
				var color = new CSSColor(rgb[0], rgb[1], rgb[2]);
				var solver = new CSSColorSolver(color);
				var result = solver.solve();
				return result.filter;
			}
			
			
			/*
			 * Sort the categories based on the sort pattern selected in options
			 *
			 */
			getItemById(id){
				var oItem;
				if(typeof this.items[id] == 'undefined'){
					oItem=new TreeviewItem();
					oItem.parentId=this.id + "_root";
					this.root.addChildId(id);
					oItem.label=id;
					oItem.tooltip = id;
					oItem.id = id;
					oItem.extraData["id"] = id;
					oItem.extraData["label"] = id;
					oItem.extraData["parentid"]="";
					this.items[oItem.id] = oItem;
				}
				return this.items[id];
			}
			
			
			get_sort_method(){
				if (this.showFoldersFirst && this.sortBy=="label") { return this.sort_folders_first_by_title;}
				if (this.showFoldersFirst && this.sortBy=="id") { return this.sort_folders_first_by_id;}
				if (!this.showFoldersFirst && this.sortBy=="label") { return this.sort_mix_folders_files_by_title;}
				if (!this.showFoldersFirst && this.sortBy=="id") { return this.sort_mix_folders_files_by_id;}
				return this.sort_as_is; 
			}
				
			sort_folders_first_by_title(a,b){
				var x = (a.isFolder() ? "0" : "1") + a.title.toLowerCase();
				var y = (b.isFolder() ? "0" : "1") + b.title.toLowerCase();
				return x === y ? 0 : x > y ? 1 : -1;
			}			
				
			sort_mix_folders_files_by_title(a,b){
				var x = a.title.toLowerCase();
				var y = b.title.toLowerCase();
				return x === y ? 0 : x > y ? 1 : -1;
			}			
					
			sort_folders_first_by_id(a,b){
				var x = (a.isFolder() ? "0" : "1") +  a.key.toLowerCase();
				var y = (b.isFolder() ? "0" : "1") + b.key.toLowerCase();
				return x === y ? 0 : x > y ? 1 : -1;
			}			
			
			sort_mix_folders_files_by_id(a,b){
				var x = a.key.toLowerCase();
				var y = b.key.toLowerCase();
				return x === y ? 0 : x > y ? 1 : -1;
			}			
			
			
			sort_as_is(a,b){
				return 0;
			}
			
			
			
			getHTML(){
				var HTML = "<style>";
				var cssClass = (this.accordionMode)  ? " accordion" : "";
				cssClass += (this.isSplunkDarkMode) ? " darkmode" : "";
				if(this.accordionMode) { 
					
					HTML += "div#" + this.id + " ul.fancytree-container >li >.fancytree-node span.fancytree-title{ background-color: " + this.accordionModeBgColor + "!important;color: " + this.accordionModeTextColor +"!important; min-width: " + this.accordionMinWidth + "px!important;}";
				} else{
					HTML += this.getCSSForCustomColors();
				}
				HTML += '</style><div class="treeview-viz ' + this.skin + cssClass + '"><div id="' + this.id + '"></div></div>';
				return HTML;
			}
			


			error_too_much_data_notice(){
				$("div#" + this.id).append('<span class="tv_error">Warning: This visualization renders up to 1,000 nested folders. Results might be truncated.</span>');
			}
			

			
			/********************************* Get data for tree ***************************************************************/
			getSource(){
				var i;
				var data = [];
				for(i=0;i<this.root.childIds.length;i++){
					data.push(this._getChildSource(this.root.childIds[i]));
				}
				return data;
			}
			
			_getChildSource(id, depth){
				if (depth === undefined) { depth = 1;}
				depth += 1;
				var data = {};
				var i;
				var oItem = this.getItemById(id);
				data.title = oItem.label;
				data.key = oItem.id;
				data.folder = oItem.hasChildren;
				data.rowdata = oItem.extraData;
				data.showIcons = this.showIcons;
	      data.selected=this.defaultSelection;
				if(typeof this.colors[oItem.color] !=='undefined') { data.extraClasses = this.colors[oItem.color];}
				if(this.skin=="custom" && oItem.hasChildren){
					data.iconFolder = oItem.iconFolder;
				}
				if (this.skin=="custom" && ! oItem.hasChildren && oItem.iconDoc !="file"){
					data.icon=  {text: ' ', addClass: 'fas fa-' + oItem.iconDoc};
				}
				data.children = [];
				for(i=0;i<oItem.childIds.length;i++){
					if(depth > 1000) { this.error_too_much_data_notice(); break;}
					data.children.push(this._getChildSource(oItem.childIds[i], depth));
				}
				return data;
			}
			/********************************* Get data for tree ***************************************************************/
			
			
			
			
			
			
			getFancytreeConfig(){
				var chkbox;
				if(this.showCheckbox && this.selectMode==1) { chkbox="radio";}
							 else{ chkbox = this.showCheckbox;}
				var config = {
					source : this.getSource(),
					checkbox: chkbox,
					imagePath: "/static/app/Splunk_TA_Cisco_Intersight/skins/skin-win8/",
					nodata: "No data was found.",
					autoCollapse: this.autoCollapse,
					treeId : this.id,
					icon: this.showIcons,
					selectMode: this.selectMode,
					clickFolderMode : 3,
					select: this.onSelectOrClick,
					click: chkbox ? null : this.onSelectOrClick,
				}
				if(this.skin=="custom"){
					config.extensions = ["glyph"];
					config.glyph =  {
						// The preset defines defaults for all supported icon types.
						// It also defines a common class name that is prepended (in this case 'fa ')
						preset: "awesome5",
						map: {
						  _addClass: "",
						  checkbox: "fas fa-square",
						  checkboxSelected: "fas fa-check-square",
						  checkboxUnknown: "fas fa-square",
						  radio: "fas fa-circle",
						  radioSelected: "fas fa-circle",
						  radioUnknown: "fas fa-dot-circle",
						  dragHelper: "fas fa-arrow-right",
						  dropMarker: "fas fa-long-arrow-right",
						  error: "fas fa-exclamation-triangle",
						  expanderClosed: "fas fa-caret-right",
						  expanderLazy: "fas fa-angle-right",
						  expanderOpen: "fas fa-caret-down",
						  loading: "fas fa-spinner fa-pulse",
						  nodata: "fas fa-meh",
						  noExpander: "",
						  // Default node icons.
						  // (Use tree.options.icon callback to define custom icons based on node data)
						  doc: "fas fa-file",
						  docOpen: "fas fa-file",
						  folder: "fas fa-folder",
						  folderOpen: "fas fa-folder-open"
						}
					}
					// Now do the custom icon method:
					config.icon=function(event, data){
						if(data.node.data.showIcons){
							if( data.node.isFolder()) {
								if (data.node.isExpanded()){
									return "fas fa-" + data.node.data.iconFolder;
								}else{
									return "fas fa-" + data.node.data.iconFolder;
								}
							}
						}else{
							return false;
						}
					}
				
				}
				return config;
			}
			


			onSelectOrClick(event, data) {
				var nodes;
				var oItem;
				var i;
				var keys;
				var j;
				var head = data.tree.tokens.tokenPrefix;
				var tail = data.tree.tokens.tokenSuffix;
				var prefix = data.tree.tokens.tokenValuePrefix;
				var suffix =  data.tree.tokens.tokenValueSuffix;
				var delimiter =  data.tree.tokens.tokenDelimiter;
				var delimiter_val = "";

				// IF we are in check box mode AND we have selected a directory THEN copy my value to ALL children
				/*if(data.options.checkbox==true && data.node.folder==true && data.node.children && typeof(event.type)=="string" && event.type=="fancytreeselect"){
					data.node.visit(function(node){node.setSelected(data.node.selected);}, false);
				}
	*/
				if(/\/search$/.test(window.location.pathname)) {return;}
				
				var aTokens={	"id": {"key": data.tree.tokens.tokenId, "value": "", values:[]},
								"label": {"key": data.tree.tokens.tokenLabel, "value": "", values:[]},
								"parentId": {"key": data.tree.tokens.tokenParentId, "value": "", values:[]},
								"click.name":{"key":"click.name", "value":"", values:[]},
								"click.value":{"key":"click.value", "value":"", values:[]},
								"click.name2":{"key":"click.name2", "value":"", values:[]},
								"click.value2":{"key":"click.value2", "value":"", values:[]}
							};
							
				if( data.options.checkbox==true ){//|| data.options.checkbox=="radio")){
					nodes= data.tree.getSelectedNodes();
				}else{
					nodes = [];
					nodes[0]=data.node;
				}
				
					
				for(i=0;i<nodes.length;i++){
					oItem = nodes[i];
					delimiter_val = (i==(nodes.length-1)) ? "" : delimiter;
					if(oItem.data.rowdata["id"]){aTokens.id.value += prefix +  oItem.data.rowdata["id"] + suffix + delimiter_val;}
					if(oItem.data.rowdata["label"]) {
						if(! aTokens.label.values[oItem.data.rowdata["label"]]){
							if(aTokens.label.value!="") {aTokens.label.value += delimiter;}
							aTokens.label.value += prefix +  oItem.data.rowdata["label"] + suffix;
							aTokens.label.values[oItem.data.rowdata["label"]] = true;
						}
					}
					if(oItem.data.rowdata["parentid"]) { 
						if(! aTokens.parentId.values[oItem.data.rowdata["parentid"]]){
							if(aTokens.parentId.value!="") {aTokens.parentId.value += delimiter;}
							aTokens.parentId.value += prefix +  oItem.data.rowdata["parentid"] + suffix;
							aTokens.parentId.values[oItem.data.rowdata["parentid"]] = true;
						}
					}
					// Do the Splunk standard tokens
					if(! aTokens["click.name"].values[oItem.data.rowdata["label"]]){
						if(aTokens["click.name"].value!="") {aTokens["click.name"].value += delimiter;}
						aTokens["click.name"].value += prefix +  oItem.data.rowdata["label"] + suffix;
						aTokens["click.name"].values[oItem.data.rowdata["label"]] = true;
					}
					
					if(! aTokens["click.value"].values[oItem.data.rowdata["id"]]){
						if(aTokens["click.value"].value!="") {aTokens["click.value"].value += delimiter;}
						aTokens["click.value"].value += prefix +  oItem.data.rowdata["id"] + suffix;
						aTokens["click.value"].values[oItem.data.rowdata["id"]] = true;
					}
					
					if(! aTokens["click.name2"].values[oItem.data.rowdata["label"]]){
						if(aTokens["click.name2"].value!="") {aTokens["click.name2"].value += delimiter;}
						aTokens["click.name2"].value += prefix +  oItem.data.rowdata["label"] + suffix;
						aTokens["click.name2"].values[oItem.data.rowdata["label"]] = true;
					}
					
					if(! aTokens["click.value2"].values[oItem.data.rowdata["id"]]){
						if(aTokens["click.value2"].value!="") {aTokens["click.value2"].value += delimiter;}
						aTokens["click.value2"].value += prefix +  oItem.data.rowdata["id"] + suffix;
						aTokens["click.value2"].values[oItem.data.rowdata["id"]] = true;
					}
					
				}	

	      // Now do the data fields for the selected node
					keys = Object.keys(data.node.data.rowdata);
	        oItem = data.node;
					for(j=0;j<keys.length;j++){
						if(! aTokens.hasOwnProperty("row." + keys[j])){
							aTokens["row." +  keys[j]]= {"key":"row." +  keys[j], "value":oItem.data.rowdata[keys[j]], values:[]};
							aTokens["row." +  keys[j]].values[oItem.data.rowdata[keys[j]]] = true;
						}else if (typeof(aTokens["row." +  keys[j]].values[oItem.data.rowdata[keys[j]]])==="undefined"){
							aTokens["row." +  keys[j]]= {"key":"row." +  keys[j], "value":oItem.data.rowdata[keys[j]], values:[]};
							aTokens["row." +  keys[j]].values[oItem.data.rowdata[keys[j]]] = true;
						}
					}

					

				var defaultTokenModel = data.tree.oMVC.Components.get('default');
				var submittedTokenModel = data.tree.oMVC.Components.get('submitted');
				
				for (var tok in aTokens) {
					
					//Add the TokenPrefix and TokenSuffix - but only if there is data. If there is no data, set the empty string
					if(aTokens[tok]['value']=="" || aTokens[tok]['value']==null){
						aTokens[tok]['value']=""
					}else{
						aTokens[tok]['value'] = head + aTokens[tok]['value']+ tail
					}
					if (defaultTokenModel) {defaultTokenModel.set(aTokens[tok]['key'],aTokens[tok]['value']);}
					if (submittedTokenModel) {submittedTokenModel.set(aTokens[tok]['key'], aTokens[tok]['value']) ;}
				}
			
				var data = {};
				data["id"] = aTokens.id.value;
				// Don't drill-down on the search page:
				if(! /treeview-viz\/search/.test(window.location.href) && typeof oItem !== "undefined"){
					oItem.tree.oSVB.drilldown({
						action: oItem.tree.oSVB.__proto__.constructor.FIELD_VALUE_DRILLDOWN, //fieldvalue
						data: data
					}, event);
				}
			
			
			}


			
		}

	//--------------------------------- CSS Color Solver Classes--------------------------------------------------------------------------------
	class CSSColor {
	  constructor(r, g, b) {
	    this.set(r, g, b);
	  }
	  
	  toString() {
	    return `rgb(${Math.round(this.r)}, ${Math.round(this.g)}, ${Math.round(this.b)})`;
	  }

	  set(r, g, b) {
	    this.r = this.clamp(r);
	    this.g = this.clamp(g);
	    this.b = this.clamp(b);
	  }

	  hueRotate(angle = 0) {
	    angle = angle / 180 * Math.PI;
	    const sin = Math.sin(angle);
	    const cos = Math.cos(angle);

	    this.multiply([
	      0.213 + cos * 0.787 - sin * 0.213,
	      0.715 - cos * 0.715 - sin * 0.715,
	      0.072 - cos * 0.072 + sin * 0.928,
	      0.213 - cos * 0.213 + sin * 0.143,
	      0.715 + cos * 0.285 + sin * 0.140,
	      0.072 - cos * 0.072 - sin * 0.283,
	      0.213 - cos * 0.213 - sin * 0.787,
	      0.715 - cos * 0.715 + sin * 0.715,
	      0.072 + cos * 0.928 + sin * 0.072,
	    ]);
	  }

	  grayscale(value = 1) {
	    this.multiply([
	      0.2126 + 0.7874 * (1 - value),
	      0.7152 - 0.7152 * (1 - value),
	      0.0722 - 0.0722 * (1 - value),
	      0.2126 - 0.2126 * (1 - value),
	      0.7152 + 0.2848 * (1 - value),
	      0.0722 - 0.0722 * (1 - value),
	      0.2126 - 0.2126 * (1 - value),
	      0.7152 - 0.7152 * (1 - value),
	      0.0722 + 0.9278 * (1 - value),
	    ]);
	  }

	  sepia(value = 1) {
	    this.multiply([
	      0.393 + 0.607 * (1 - value),
	      0.769 - 0.769 * (1 - value),
	      0.189 - 0.189 * (1 - value),
	      0.349 - 0.349 * (1 - value),
	      0.686 + 0.314 * (1 - value),
	      0.168 - 0.168 * (1 - value),
	      0.272 - 0.272 * (1 - value),
	      0.534 - 0.534 * (1 - value),
	      0.131 + 0.869 * (1 - value),
	    ]);
	  }

	  saturate(value = 1) {
	    this.multiply([
	      0.213 + 0.787 * value,
	      0.715 - 0.715 * value,
	      0.072 - 0.072 * value,
	      0.213 - 0.213 * value,
	      0.715 + 0.285 * value,
	      0.072 - 0.072 * value,
	      0.213 - 0.213 * value,
	      0.715 - 0.715 * value,
	      0.072 + 0.928 * value,
	    ]);
	  }

	  multiply(matrix) {
	    const newR = this.clamp(this.r * matrix[0] + this.g * matrix[1] + this.b * matrix[2]);
	    const newG = this.clamp(this.r * matrix[3] + this.g * matrix[4] + this.b * matrix[5]);
	    const newB = this.clamp(this.r * matrix[6] + this.g * matrix[7] + this.b * matrix[8]);
	    this.r = newR;
	    this.g = newG;
	    this.b = newB;
	  }

	  brightness(value = 1) {
	    this.linear(value);
	  }
	  contrast(value = 1) {
	    this.linear(value, -(0.5 * value) + 0.5);
	  }

	  linear(slope = 1, intercept = 0) {
	    this.r = this.clamp(this.r * slope + intercept * 255);
	    this.g = this.clamp(this.g * slope + intercept * 255);
	    this.b = this.clamp(this.b * slope + intercept * 255);
	  }

	  invert(value = 1) {
	    this.r = this.clamp((value + this.r / 255 * (1 - 2 * value)) * 255);
	    this.g = this.clamp((value + this.g / 255 * (1 - 2 * value)) * 255);
	    this.b = this.clamp((value + this.b / 255 * (1 - 2 * value)) * 255);
	  }

	  hsl() {
	    // Code taken from https://stackoverflow.com/a/9493060/2688027, licensed under CC BY-SA.
	    const r = this.r / 255;
	    const g = this.g / 255;
	    const b = this.b / 255;
	    const max = Math.max(r, g, b);
	    const min = Math.min(r, g, b);
	    let h, s, l = (max + min) / 2;

	    if (max === min) {
	      h = s = 0;
	    } else {
	      const d = max - min;
	      s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
	      switch (max) {
	        case r:
	          h = (g - b) / d + (g < b ? 6 : 0);
	          break;

	        case g:
	          h = (b - r) / d + 2;
	          break;

	        case b:
	          h = (r - g) / d + 4;
	          break;
	      }
	      h /= 6;
	    }

	    return {
	      h: h * 100,
	      s: s * 100,
	      l: l * 100,
	    };
	  }

	  clamp(value) {
	    if (value > 255) {
	      value = 255;
	    } else if (value < 0) {
	      value = 0;
	    }
	    return value;
	  }
	}

	class CSSColorSolver {
	  constructor(target, baseColor) {
	    this.target = target;
	    this.targetHSL = target.hsl();
	    this.reusedColor = new CSSColor(0, 0, 0);
	  }

	  solve() {
	    const result = this.solveNarrow(this.solveWide());
	    return {
	      values: result.values,
	      loss: result.loss,
	      filter: this.css(result.values),
	    };
	  }

	  solveWide() {
	    const A = 5;
	    const c = 15;
	    const a = [60, 180, 18000, 600, 1.2, 1.2];

	    let best = { loss: Infinity };
	    for (let i = 0; best.loss > 25 && i < 3; i++) {
	      const initial = [50, 20, 3750, 50, 100, 100];
	      const result = this.spsa(A, a, c, initial, 1000);
	      if (result.loss < best.loss) {
	        best = result;
	      }
	    }
	    return best;
	  }

	  solveNarrow(wide) {
	    const A = wide.loss;
	    const c = 2;
	    const A1 = A + 1;
	    const a = [0.25 * A1, 0.25 * A1, A1, 0.25 * A1, 0.2 * A1, 0.2 * A1];
	    return this.spsa(A, a, c, wide.values, 500);
	  }

	  spsa(A, a, c, values, iters) {
	    const alpha = 1;
	    const gamma = 0.16666666666666666;

	    let best = null;
	    let bestLoss = Infinity;
	    const deltas = new Array(6);
	    const highArgs = new Array(6);
	    const lowArgs = new Array(6);

	    for (let k = 0; k < iters; k++) {
	      const ck = c / Math.pow(k + 1, gamma);
	      for (let i = 0; i < 6; i++) {
	        deltas[i] = Math.random() > 0.5 ? 1 : -1;
	        highArgs[i] = values[i] + ck * deltas[i];
	        lowArgs[i] = values[i] - ck * deltas[i];
	      }

	      const lossDiff = this.loss(highArgs) - this.loss(lowArgs);
	      for (let i = 0; i < 6; i++) {
	        const g = lossDiff / (2 * ck) * deltas[i];
	        const ak = a[i] / Math.pow(A + k + 1, alpha);
	        values[i] = fix(values[i] - ak * g, i);
	      }

	      const loss = this.loss(values);
	      if (loss < bestLoss) {
	        best = values.slice(0);
	        bestLoss = loss;
	      }
	    }
	    return { values: best, loss: bestLoss };

	    function fix(value, idx) {
	      let max = 100;
	      if (idx === 2 /* saturate */) {
	        max = 7500;
	      } else if (idx === 4 /* brightness */ || idx === 5 /* contrast */) {
	        max = 200;
	      }

	      if (idx === 3 /* hue-rotate */) {
	        if (value > max) {
	          value %= max;
	        } else if (value < 0) {
	          value = max + value % max;
	        }
	      } else if (value < 0) {
	        value = 0;
	      } else if (value > max) {
	        value = max;
	      }
	      return value;
	    }
	  }

	  loss(filters) {
	    // Argument is array of percentages.
	    const color = this.reusedColor;
	    color.set(0, 0, 0);

	    color.invert(filters[0] / 100);
	    color.sepia(filters[1] / 100);
	    color.saturate(filters[2] / 100);
	    color.hueRotate(filters[3] * 3.6);
	    color.brightness(filters[4] / 100);
	    color.contrast(filters[5] / 100);

	    const colorHSL = color.hsl();
	    return (
	      Math.abs(color.r - this.target.r) +
	      Math.abs(color.g - this.target.g) +
	      Math.abs(color.b - this.target.b) +
	      Math.abs(colorHSL.h - this.targetHSL.h) +
	      Math.abs(colorHSL.s - this.targetHSL.s) +
	      Math.abs(colorHSL.l - this.targetHSL.l)
	    );
	  }

	  css(filters) {
	    function fmt(idx, multiplier = 1) {
	      return Math.round(filters[idx] * multiplier);
	    }
	    return `filter: brightness(0) saturate(100%) invert(${fmt(0)}%) sepia(${fmt(1)}%) saturate(${fmt(2)}%) hue-rotate(${fmt(3, 3.6)}deg) brightness(${fmt(4)}%) contrast(${fmt(5)}%);`;
	  }
	}



		module.exports = { TreeviewItem, TreeviewViz,CSSColor, CSSColorSolver}


/***/ }),
/* 2 */
/***/ (function(module, exports) {

	module.exports = __WEBPACK_EXTERNAL_MODULE_2__;

/***/ }),
/* 3 */
/***/ (function(module, exports, __webpack_require__) {

	var __WEBPACK_AMD_DEFINE_ARRAY__, __WEBPACK_AMD_DEFINE_RESULT__;/*!
	 * jQuery JavaScript Library v3.7.1
	 * https://jquery.com/
	 *
	 * Copyright OpenJS Foundation and other contributors
	 * Released under the MIT license
	 * https://jquery.org/license
	 *
	 * Date: 2023-08-28T13:37Z
	 */
	( function( global, factory ) {

		"use strict";

		if ( typeof module === "object" && typeof module.exports === "object" ) {

			// For CommonJS and CommonJS-like environments where a proper `window`
			// is present, execute the factory and get jQuery.
			// For environments that do not have a `window` with a `document`
			// (such as Node.js), expose a factory as module.exports.
			// This accentuates the need for the creation of a real `window`.
			// e.g. var jQuery = require("jquery")(window);
			// See ticket trac-14549 for more info.
			module.exports = global.document ?
				factory( global, true ) :
				function( w ) {
					if ( !w.document ) {
						throw new Error( "jQuery requires a window with a document" );
					}
					return factory( w );
				};
		} else {
			factory( global );
		}

	// Pass this if window is not defined yet
	} )( typeof window !== "undefined" ? window : this, function( window, noGlobal ) {

	// Edge <= 12 - 13+, Firefox <=18 - 45+, IE 10 - 11, Safari 5.1 - 9+, iOS 6 - 9.1
	// throw exceptions when non-strict code (e.g., ASP.NET 4.5) accesses strict mode
	// arguments.callee.caller (trac-13335). But as of jQuery 3.0 (2016), strict mode should be common
	// enough that all such attempts are guarded in a try block.
	"use strict";

	var arr = [];

	var getProto = Object.getPrototypeOf;

	var slice = arr.slice;

	var flat = arr.flat ? function( array ) {
		return arr.flat.call( array );
	} : function( array ) {
		return arr.concat.apply( [], array );
	};


	var push = arr.push;

	var indexOf = arr.indexOf;

	var class2type = {};

	var toString = class2type.toString;

	var hasOwn = class2type.hasOwnProperty;

	var fnToString = hasOwn.toString;

	var ObjectFunctionString = fnToString.call( Object );

	var support = {};

	var isFunction = function isFunction( obj ) {

			// Support: Chrome <=57, Firefox <=52
			// In some browsers, typeof returns "function" for HTML <object> elements
			// (i.e., `typeof document.createElement( "object" ) === "function"`).
			// We don't want to classify *any* DOM node as a function.
			// Support: QtWeb <=3.8.5, WebKit <=534.34, wkhtmltopdf tool <=0.12.5
			// Plus for old WebKit, typeof returns "function" for HTML collections
			// (e.g., `typeof document.getElementsByTagName("div") === "function"`). (gh-4756)
			return typeof obj === "function" && typeof obj.nodeType !== "number" &&
				typeof obj.item !== "function";
		};


	var isWindow = function isWindow( obj ) {
			return obj != null && obj === obj.window;
		};


	var document = window.document;



		var preservedScriptAttributes = {
			type: true,
			src: true,
			nonce: true,
			noModule: true
		};

		function DOMEval( code, node, doc ) {
			doc = doc || document;

			var i, val,
				script = doc.createElement( "script" );

			script.text = code;
			if ( node ) {
				for ( i in preservedScriptAttributes ) {

					// Support: Firefox 64+, Edge 18+
					// Some browsers don't support the "nonce" property on scripts.
					// On the other hand, just using `getAttribute` is not enough as
					// the `nonce` attribute is reset to an empty string whenever it
					// becomes browsing-context connected.
					// See https://github.com/whatwg/html/issues/2369
					// See https://html.spec.whatwg.org/#nonce-attributes
					// The `node.getAttribute` check was added for the sake of
					// `jQuery.globalEval` so that it can fake a nonce-containing node
					// via an object.
					val = node[ i ] || node.getAttribute && node.getAttribute( i );
					if ( val ) {
						script.setAttribute( i, val );
					}
				}
			}
			doc.head.appendChild( script ).parentNode.removeChild( script );
		}


	function toType( obj ) {
		if ( obj == null ) {
			return obj + "";
		}

		// Support: Android <=2.3 only (functionish RegExp)
		return typeof obj === "object" || typeof obj === "function" ?
			class2type[ toString.call( obj ) ] || "object" :
			typeof obj;
	}
	/* global Symbol */
	// Defining this global in .eslintrc.json would create a danger of using the global
	// unguarded in another place, it seems safer to define global only for this module



	var version = "3.7.1",

		rhtmlSuffix = /HTML$/i,

		// Define a local copy of jQuery
		jQuery = function( selector, context ) {

			// The jQuery object is actually just the init constructor 'enhanced'
			// Need init if jQuery is called (just allow error to be thrown if not included)
			return new jQuery.fn.init( selector, context );
		};

	jQuery.fn = jQuery.prototype = {

		// The current version of jQuery being used
		jquery: version,

		constructor: jQuery,

		// The default length of a jQuery object is 0
		length: 0,

		toArray: function() {
			return slice.call( this );
		},

		// Get the Nth element in the matched element set OR
		// Get the whole matched element set as a clean array
		get: function( num ) {

			// Return all the elements in a clean array
			if ( num == null ) {
				return slice.call( this );
			}

			// Return just the one element from the set
			return num < 0 ? this[ num + this.length ] : this[ num ];
		},

		// Take an array of elements and push it onto the stack
		// (returning the new matched element set)
		pushStack: function( elems ) {

			// Build a new jQuery matched element set
			var ret = jQuery.merge( this.constructor(), elems );

			// Add the old object onto the stack (as a reference)
			ret.prevObject = this;

			// Return the newly-formed element set
			return ret;
		},

		// Execute a callback for every element in the matched set.
		each: function( callback ) {
			return jQuery.each( this, callback );
		},

		map: function( callback ) {
			return this.pushStack( jQuery.map( this, function( elem, i ) {
				return callback.call( elem, i, elem );
			} ) );
		},

		slice: function() {
			return this.pushStack( slice.apply( this, arguments ) );
		},

		first: function() {
			return this.eq( 0 );
		},

		last: function() {
			return this.eq( -1 );
		},

		even: function() {
			return this.pushStack( jQuery.grep( this, function( _elem, i ) {
				return ( i + 1 ) % 2;
			} ) );
		},

		odd: function() {
			return this.pushStack( jQuery.grep( this, function( _elem, i ) {
				return i % 2;
			} ) );
		},

		eq: function( i ) {
			var len = this.length,
				j = +i + ( i < 0 ? len : 0 );
			return this.pushStack( j >= 0 && j < len ? [ this[ j ] ] : [] );
		},

		end: function() {
			return this.prevObject || this.constructor();
		},

		// For internal use only.
		// Behaves like an Array's method, not like a jQuery method.
		push: push,
		sort: arr.sort,
		splice: arr.splice
	};

	jQuery.extend = jQuery.fn.extend = function() {
		var options, name, src, copy, copyIsArray, clone,
			target = arguments[ 0 ] || {},
			i = 1,
			length = arguments.length,
			deep = false;

		// Handle a deep copy situation
		if ( typeof target === "boolean" ) {
			deep = target;

			// Skip the boolean and the target
			target = arguments[ i ] || {};
			i++;
		}

		// Handle case when target is a string or something (possible in deep copy)
		if ( typeof target !== "object" && !isFunction( target ) ) {
			target = {};
		}

		// Extend jQuery itself if only one argument is passed
		if ( i === length ) {
			target = this;
			i--;
		}

		for ( ; i < length; i++ ) {

			// Only deal with non-null/undefined values
			if ( ( options = arguments[ i ] ) != null ) {

				// Extend the base object
				for ( name in options ) {
					copy = options[ name ];

					// Prevent Object.prototype pollution
					// Prevent never-ending loop
					if ( name === "__proto__" || target === copy ) {
						continue;
					}

					// Recurse if we're merging plain objects or arrays
					if ( deep && copy && ( jQuery.isPlainObject( copy ) ||
						( copyIsArray = Array.isArray( copy ) ) ) ) {
						src = target[ name ];

						// Ensure proper type for the source value
						if ( copyIsArray && !Array.isArray( src ) ) {
							clone = [];
						} else if ( !copyIsArray && !jQuery.isPlainObject( src ) ) {
							clone = {};
						} else {
							clone = src;
						}
						copyIsArray = false;

						// Never move original objects, clone them
						target[ name ] = jQuery.extend( deep, clone, copy );

					// Don't bring in undefined values
					} else if ( copy !== undefined ) {
						target[ name ] = copy;
					}
				}
			}
		}

		// Return the modified object
		return target;
	};

	jQuery.extend( {

		// Unique for each copy of jQuery on the page
		expando: "jQuery" + ( version + Math.random() ).replace( /\D/g, "" ),

		// Assume jQuery is ready without the ready module
		isReady: true,

		error: function( msg ) {
			throw new Error( msg );
		},

		noop: function() {},

		isPlainObject: function( obj ) {
			var proto, Ctor;

			// Detect obvious negatives
			// Use toString instead of jQuery.type to catch host objects
			if ( !obj || toString.call( obj ) !== "[object Object]" ) {
				return false;
			}

			proto = getProto( obj );

			// Objects with no prototype (e.g., `Object.create( null )`) are plain
			if ( !proto ) {
				return true;
			}

			// Objects with prototype are plain iff they were constructed by a global Object function
			Ctor = hasOwn.call( proto, "constructor" ) && proto.constructor;
			return typeof Ctor === "function" && fnToString.call( Ctor ) === ObjectFunctionString;
		},

		isEmptyObject: function( obj ) {
			var name;

			for ( name in obj ) {
				return false;
			}
			return true;
		},

		// Evaluates a script in a provided context; falls back to the global one
		// if not specified.
		globalEval: function( code, options, doc ) {
			DOMEval( code, { nonce: options && options.nonce }, doc );
		},

		each: function( obj, callback ) {
			var length, i = 0;

			if ( isArrayLike( obj ) ) {
				length = obj.length;
				for ( ; i < length; i++ ) {
					if ( callback.call( obj[ i ], i, obj[ i ] ) === false ) {
						break;
					}
				}
			} else {
				for ( i in obj ) {
					if ( callback.call( obj[ i ], i, obj[ i ] ) === false ) {
						break;
					}
				}
			}

			return obj;
		},


		// Retrieve the text value of an array of DOM nodes
		text: function( elem ) {
			var node,
				ret = "",
				i = 0,
				nodeType = elem.nodeType;

			if ( !nodeType ) {

				// If no nodeType, this is expected to be an array
				while ( ( node = elem[ i++ ] ) ) {

					// Do not traverse comment nodes
					ret += jQuery.text( node );
				}
			}
			if ( nodeType === 1 || nodeType === 11 ) {
				return elem.textContent;
			}
			if ( nodeType === 9 ) {
				return elem.documentElement.textContent;
			}
			if ( nodeType === 3 || nodeType === 4 ) {
				return elem.nodeValue;
			}

			// Do not include comment or processing instruction nodes

			return ret;
		},

		// results is for internal usage only
		makeArray: function( arr, results ) {
			var ret = results || [];

			if ( arr != null ) {
				if ( isArrayLike( Object( arr ) ) ) {
					jQuery.merge( ret,
						typeof arr === "string" ?
							[ arr ] : arr
					);
				} else {
					push.call( ret, arr );
				}
			}

			return ret;
		},

		inArray: function( elem, arr, i ) {
			return arr == null ? -1 : indexOf.call( arr, elem, i );
		},

		isXMLDoc: function( elem ) {
			var namespace = elem && elem.namespaceURI,
				docElem = elem && ( elem.ownerDocument || elem ).documentElement;

			// Assume HTML when documentElement doesn't yet exist, such as inside
			// document fragments.
			return !rhtmlSuffix.test( namespace || docElem && docElem.nodeName || "HTML" );
		},

		// Support: Android <=4.0 only, PhantomJS 1 only
		// push.apply(_, arraylike) throws on ancient WebKit
		merge: function( first, second ) {
			var len = +second.length,
				j = 0,
				i = first.length;

			for ( ; j < len; j++ ) {
				first[ i++ ] = second[ j ];
			}

			first.length = i;

			return first;
		},

		grep: function( elems, callback, invert ) {
			var callbackInverse,
				matches = [],
				i = 0,
				length = elems.length,
				callbackExpect = !invert;

			// Go through the array, only saving the items
			// that pass the validator function
			for ( ; i < length; i++ ) {
				callbackInverse = !callback( elems[ i ], i );
				if ( callbackInverse !== callbackExpect ) {
					matches.push( elems[ i ] );
				}
			}

			return matches;
		},

		// arg is for internal usage only
		map: function( elems, callback, arg ) {
			var length, value,
				i = 0,
				ret = [];

			// Go through the array, translating each of the items to their new values
			if ( isArrayLike( elems ) ) {
				length = elems.length;
				for ( ; i < length; i++ ) {
					value = callback( elems[ i ], i, arg );

					if ( value != null ) {
						ret.push( value );
					}
				}

			// Go through every key on the object,
			} else {
				for ( i in elems ) {
					value = callback( elems[ i ], i, arg );

					if ( value != null ) {
						ret.push( value );
					}
				}
			}

			// Flatten any nested arrays
			return flat( ret );
		},

		// A global GUID counter for objects
		guid: 1,

		// jQuery.support is not used in Core but other projects attach their
		// properties to it so it needs to exist.
		support: support
	} );

	if ( typeof Symbol === "function" ) {
		jQuery.fn[ Symbol.iterator ] = arr[ Symbol.iterator ];
	}

	// Populate the class2type map
	jQuery.each( "Boolean Number String Function Array Date RegExp Object Error Symbol".split( " " ),
		function( _i, name ) {
			class2type[ "[object " + name + "]" ] = name.toLowerCase();
		} );

	function isArrayLike( obj ) {

		// Support: real iOS 8.2 only (not reproducible in simulator)
		// `in` check used to prevent JIT error (gh-2145)
		// hasOwn isn't used here due to false negatives
		// regarding Nodelist length in IE
		var length = !!obj && "length" in obj && obj.length,
			type = toType( obj );

		if ( isFunction( obj ) || isWindow( obj ) ) {
			return false;
		}

		return type === "array" || length === 0 ||
			typeof length === "number" && length > 0 && ( length - 1 ) in obj;
	}


	function nodeName( elem, name ) {

		return elem.nodeName && elem.nodeName.toLowerCase() === name.toLowerCase();

	}
	var pop = arr.pop;


	var sort = arr.sort;


	var splice = arr.splice;


	var whitespace = "[\\x20\\t\\r\\n\\f]";


	var rtrimCSS = new RegExp(
		"^" + whitespace + "+|((?:^|[^\\\\])(?:\\\\.)*)" + whitespace + "+$",
		"g"
	);




	// Note: an element does not contain itself
	jQuery.contains = function( a, b ) {
		var bup = b && b.parentNode;

		return a === bup || !!( bup && bup.nodeType === 1 && (

			// Support: IE 9 - 11+
			// IE doesn't have `contains` on SVG.
			a.contains ?
				a.contains( bup ) :
				a.compareDocumentPosition && a.compareDocumentPosition( bup ) & 16
		) );
	};




	// CSS string/identifier serialization
	// https://drafts.csswg.org/cssom/#common-serializing-idioms
	var rcssescape = /([\0-\x1f\x7f]|^-?\d)|^-$|[^\x80-\uFFFF\w-]/g;

	function fcssescape( ch, asCodePoint ) {
		if ( asCodePoint ) {

			// U+0000 NULL becomes U+FFFD REPLACEMENT CHARACTER
			if ( ch === "\0" ) {
				return "\uFFFD";
			}

			// Control characters and (dependent upon position) numbers get escaped as code points
			return ch.slice( 0, -1 ) + "\\" + ch.charCodeAt( ch.length - 1 ).toString( 16 ) + " ";
		}

		// Other potentially-special ASCII characters get backslash-escaped
		return "\\" + ch;
	}

	jQuery.escapeSelector = function( sel ) {
		return ( sel + "" ).replace( rcssescape, fcssescape );
	};




	var preferredDoc = document,
		pushNative = push;

	( function() {

	var i,
		Expr,
		outermostContext,
		sortInput,
		hasDuplicate,
		push = pushNative,

		// Local document vars
		document,
		documentElement,
		documentIsHTML,
		rbuggyQSA,
		matches,

		// Instance-specific data
		expando = jQuery.expando,
		dirruns = 0,
		done = 0,
		classCache = createCache(),
		tokenCache = createCache(),
		compilerCache = createCache(),
		nonnativeSelectorCache = createCache(),
		sortOrder = function( a, b ) {
			if ( a === b ) {
				hasDuplicate = true;
			}
			return 0;
		},

		booleans = "checked|selected|async|autofocus|autoplay|controls|defer|disabled|hidden|ismap|" +
			"loop|multiple|open|readonly|required|scoped",

		// Regular expressions

		// https://www.w3.org/TR/css-syntax-3/#ident-token-diagram
		identifier = "(?:\\\\[\\da-fA-F]{1,6}" + whitespace +
			"?|\\\\[^\\r\\n\\f]|[\\w-]|[^\0-\\x7f])+",

		// Attribute selectors: https://www.w3.org/TR/selectors/#attribute-selectors
		attributes = "\\[" + whitespace + "*(" + identifier + ")(?:" + whitespace +

			// Operator (capture 2)
			"*([*^$|!~]?=)" + whitespace +

			// "Attribute values must be CSS identifiers [capture 5] or strings [capture 3 or capture 4]"
			"*(?:'((?:\\\\.|[^\\\\'])*)'|\"((?:\\\\.|[^\\\\\"])*)\"|(" + identifier + "))|)" +
			whitespace + "*\\]",

		pseudos = ":(" + identifier + ")(?:\\((" +

			// To reduce the number of selectors needing tokenize in the preFilter, prefer arguments:
			// 1. quoted (capture 3; capture 4 or capture 5)
			"('((?:\\\\.|[^\\\\'])*)'|\"((?:\\\\.|[^\\\\\"])*)\")|" +

			// 2. simple (capture 6)
			"((?:\\\\.|[^\\\\()[\\]]|" + attributes + ")*)|" +

			// 3. anything else (capture 2)
			".*" +
			")\\)|)",

		// Leading and non-escaped trailing whitespace, capturing some non-whitespace characters preceding the latter
		rwhitespace = new RegExp( whitespace + "+", "g" ),

		rcomma = new RegExp( "^" + whitespace + "*," + whitespace + "*" ),
		rleadingCombinator = new RegExp( "^" + whitespace + "*([>+~]|" + whitespace + ")" +
			whitespace + "*" ),
		rdescend = new RegExp( whitespace + "|>" ),

		rpseudo = new RegExp( pseudos ),
		ridentifier = new RegExp( "^" + identifier + "$" ),

		matchExpr = {
			ID: new RegExp( "^#(" + identifier + ")" ),
			CLASS: new RegExp( "^\\.(" + identifier + ")" ),
			TAG: new RegExp( "^(" + identifier + "|[*])" ),
			ATTR: new RegExp( "^" + attributes ),
			PSEUDO: new RegExp( "^" + pseudos ),
			CHILD: new RegExp(
				"^:(only|first|last|nth|nth-last)-(child|of-type)(?:\\(" +
					whitespace + "*(even|odd|(([+-]|)(\\d*)n|)" + whitespace + "*(?:([+-]|)" +
					whitespace + "*(\\d+)|))" + whitespace + "*\\)|)", "i" ),
			bool: new RegExp( "^(?:" + booleans + ")$", "i" ),

			// For use in libraries implementing .is()
			// We use this for POS matching in `select`
			needsContext: new RegExp( "^" + whitespace +
				"*[>+~]|:(even|odd|eq|gt|lt|nth|first|last)(?:\\(" + whitespace +
				"*((?:-\\d)?\\d*)" + whitespace + "*\\)|)(?=[^-]|$)", "i" )
		},

		rinputs = /^(?:input|select|textarea|button)$/i,
		rheader = /^h\d$/i,

		// Easily-parseable/retrievable ID or TAG or CLASS selectors
		rquickExpr = /^(?:#([\w-]+)|(\w+)|\.([\w-]+))$/,

		rsibling = /[+~]/,

		// CSS escapes
		// https://www.w3.org/TR/CSS21/syndata.html#escaped-characters
		runescape = new RegExp( "\\\\[\\da-fA-F]{1,6}" + whitespace +
			"?|\\\\([^\\r\\n\\f])", "g" ),
		funescape = function( escape, nonHex ) {
			var high = "0x" + escape.slice( 1 ) - 0x10000;

			if ( nonHex ) {

				// Strip the backslash prefix from a non-hex escape sequence
				return nonHex;
			}

			// Replace a hexadecimal escape sequence with the encoded Unicode code point
			// Support: IE <=11+
			// For values outside the Basic Multilingual Plane (BMP), manually construct a
			// surrogate pair
			return high < 0 ?
				String.fromCharCode( high + 0x10000 ) :
				String.fromCharCode( high >> 10 | 0xD800, high & 0x3FF | 0xDC00 );
		},

		// Used for iframes; see `setDocument`.
		// Support: IE 9 - 11+, Edge 12 - 18+
		// Removing the function wrapper causes a "Permission Denied"
		// error in IE/Edge.
		unloadHandler = function() {
			setDocument();
		},

		inDisabledFieldset = addCombinator(
			function( elem ) {
				return elem.disabled === true && nodeName( elem, "fieldset" );
			},
			{ dir: "parentNode", next: "legend" }
		);

	// Support: IE <=9 only
	// Accessing document.activeElement can throw unexpectedly
	// https://bugs.jquery.com/ticket/13393
	function safeActiveElement() {
		try {
			return document.activeElement;
		} catch ( err ) { }
	}

	// Optimize for push.apply( _, NodeList )
	try {
		push.apply(
			( arr = slice.call( preferredDoc.childNodes ) ),
			preferredDoc.childNodes
		);

		// Support: Android <=4.0
		// Detect silently failing push.apply
		// eslint-disable-next-line no-unused-expressions
		arr[ preferredDoc.childNodes.length ].nodeType;
	} catch ( e ) {
		push = {
			apply: function( target, els ) {
				pushNative.apply( target, slice.call( els ) );
			},
			call: function( target ) {
				pushNative.apply( target, slice.call( arguments, 1 ) );
			}
		};
	}

	function find( selector, context, results, seed ) {
		var m, i, elem, nid, match, groups, newSelector,
			newContext = context && context.ownerDocument,

			// nodeType defaults to 9, since context defaults to document
			nodeType = context ? context.nodeType : 9;

		results = results || [];

		// Return early from calls with invalid selector or context
		if ( typeof selector !== "string" || !selector ||
			nodeType !== 1 && nodeType !== 9 && nodeType !== 11 ) {

			return results;
		}

		// Try to shortcut find operations (as opposed to filters) in HTML documents
		if ( !seed ) {
			setDocument( context );
			context = context || document;

			if ( documentIsHTML ) {

				// If the selector is sufficiently simple, try using a "get*By*" DOM method
				// (excepting DocumentFragment context, where the methods don't exist)
				if ( nodeType !== 11 && ( match = rquickExpr.exec( selector ) ) ) {

					// ID selector
					if ( ( m = match[ 1 ] ) ) {

						// Document context
						if ( nodeType === 9 ) {
							if ( ( elem = context.getElementById( m ) ) ) {

								// Support: IE 9 only
								// getElementById can match elements by name instead of ID
								if ( elem.id === m ) {
									push.call( results, elem );
									return results;
								}
							} else {
								return results;
							}

						// Element context
						} else {

							// Support: IE 9 only
							// getElementById can match elements by name instead of ID
							if ( newContext && ( elem = newContext.getElementById( m ) ) &&
								find.contains( context, elem ) &&
								elem.id === m ) {

								push.call( results, elem );
								return results;
							}
						}

					// Type selector
					} else if ( match[ 2 ] ) {
						push.apply( results, context.getElementsByTagName( selector ) );
						return results;

					// Class selector
					} else if ( ( m = match[ 3 ] ) && context.getElementsByClassName ) {
						push.apply( results, context.getElementsByClassName( m ) );
						return results;
					}
				}

				// Take advantage of querySelectorAll
				if ( !nonnativeSelectorCache[ selector + " " ] &&
					( !rbuggyQSA || !rbuggyQSA.test( selector ) ) ) {

					newSelector = selector;
					newContext = context;

					// qSA considers elements outside a scoping root when evaluating child or
					// descendant combinators, which is not what we want.
					// In such cases, we work around the behavior by prefixing every selector in the
					// list with an ID selector referencing the scope context.
					// The technique has to be used as well when a leading combinator is used
					// as such selectors are not recognized by querySelectorAll.
					// Thanks to Andrew Dupont for this technique.
					if ( nodeType === 1 &&
						( rdescend.test( selector ) || rleadingCombinator.test( selector ) ) ) {

						// Expand context for sibling selectors
						newContext = rsibling.test( selector ) && testContext( context.parentNode ) ||
							context;

						// We can use :scope instead of the ID hack if the browser
						// supports it & if we're not changing the context.
						// Support: IE 11+, Edge 17 - 18+
						// IE/Edge sometimes throw a "Permission denied" error when
						// strict-comparing two documents; shallow comparisons work.
						// eslint-disable-next-line eqeqeq
						if ( newContext != context || !support.scope ) {

							// Capture the context ID, setting it first if necessary
							if ( ( nid = context.getAttribute( "id" ) ) ) {
								nid = jQuery.escapeSelector( nid );
							} else {
								context.setAttribute( "id", ( nid = expando ) );
							}
						}

						// Prefix every selector in the list
						groups = tokenize( selector );
						i = groups.length;
						while ( i-- ) {
							groups[ i ] = ( nid ? "#" + nid : ":scope" ) + " " +
								toSelector( groups[ i ] );
						}
						newSelector = groups.join( "," );
					}

					try {
						push.apply( results,
							newContext.querySelectorAll( newSelector )
						);
						return results;
					} catch ( qsaError ) {
						nonnativeSelectorCache( selector, true );
					} finally {
						if ( nid === expando ) {
							context.removeAttribute( "id" );
						}
					}
				}
			}
		}

		// All others
		return select( selector.replace( rtrimCSS, "$1" ), context, results, seed );
	}

	/**
	 * Create key-value caches of limited size
	 * @returns {function(string, object)} Returns the Object data after storing it on itself with
	 *	property name the (space-suffixed) string and (if the cache is larger than Expr.cacheLength)
	 *	deleting the oldest entry
	 */
	function createCache() {
		var keys = [];

		function cache( key, value ) {

			// Use (key + " ") to avoid collision with native prototype properties
			// (see https://github.com/jquery/sizzle/issues/157)
			if ( keys.push( key + " " ) > Expr.cacheLength ) {

				// Only keep the most recent entries
				delete cache[ keys.shift() ];
			}
			return ( cache[ key + " " ] = value );
		}
		return cache;
	}

	/**
	 * Mark a function for special use by jQuery selector module
	 * @param {Function} fn The function to mark
	 */
	function markFunction( fn ) {
		fn[ expando ] = true;
		return fn;
	}

	/**
	 * Support testing using an element
	 * @param {Function} fn Passed the created element and returns a boolean result
	 */
	function assert( fn ) {
		var el = document.createElement( "fieldset" );

		try {
			return !!fn( el );
		} catch ( e ) {
			return false;
		} finally {

			// Remove from its parent by default
			if ( el.parentNode ) {
				el.parentNode.removeChild( el );
			}

			// release memory in IE
			el = null;
		}
	}

	/**
	 * Returns a function to use in pseudos for input types
	 * @param {String} type
	 */
	function createInputPseudo( type ) {
		return function( elem ) {
			return nodeName( elem, "input" ) && elem.type === type;
		};
	}

	/**
	 * Returns a function to use in pseudos for buttons
	 * @param {String} type
	 */
	function createButtonPseudo( type ) {
		return function( elem ) {
			return ( nodeName( elem, "input" ) || nodeName( elem, "button" ) ) &&
				elem.type === type;
		};
	}

	/**
	 * Returns a function to use in pseudos for :enabled/:disabled
	 * @param {Boolean} disabled true for :disabled; false for :enabled
	 */
	function createDisabledPseudo( disabled ) {

		// Known :disabled false positives: fieldset[disabled] > legend:nth-of-type(n+2) :can-disable
		return function( elem ) {

			// Only certain elements can match :enabled or :disabled
			// https://html.spec.whatwg.org/multipage/scripting.html#selector-enabled
			// https://html.spec.whatwg.org/multipage/scripting.html#selector-disabled
			if ( "form" in elem ) {

				// Check for inherited disabledness on relevant non-disabled elements:
				// * listed form-associated elements in a disabled fieldset
				//   https://html.spec.whatwg.org/multipage/forms.html#category-listed
				//   https://html.spec.whatwg.org/multipage/forms.html#concept-fe-disabled
				// * option elements in a disabled optgroup
				//   https://html.spec.whatwg.org/multipage/forms.html#concept-option-disabled
				// All such elements have a "form" property.
				if ( elem.parentNode && elem.disabled === false ) {

					// Option elements defer to a parent optgroup if present
					if ( "label" in elem ) {
						if ( "label" in elem.parentNode ) {
							return elem.parentNode.disabled === disabled;
						} else {
							return elem.disabled === disabled;
						}
					}

					// Support: IE 6 - 11+
					// Use the isDisabled shortcut property to check for disabled fieldset ancestors
					return elem.isDisabled === disabled ||

						// Where there is no isDisabled, check manually
						elem.isDisabled !== !disabled &&
							inDisabledFieldset( elem ) === disabled;
				}

				return elem.disabled === disabled;

			// Try to winnow out elements that can't be disabled before trusting the disabled property.
			// Some victims get caught in our net (label, legend, menu, track), but it shouldn't
			// even exist on them, let alone have a boolean value.
			} else if ( "label" in elem ) {
				return elem.disabled === disabled;
			}

			// Remaining elements are neither :enabled nor :disabled
			return false;
		};
	}

	/**
	 * Returns a function to use in pseudos for positionals
	 * @param {Function} fn
	 */
	function createPositionalPseudo( fn ) {
		return markFunction( function( argument ) {
			argument = +argument;
			return markFunction( function( seed, matches ) {
				var j,
					matchIndexes = fn( [], seed.length, argument ),
					i = matchIndexes.length;

				// Match elements found at the specified indexes
				while ( i-- ) {
					if ( seed[ ( j = matchIndexes[ i ] ) ] ) {
						seed[ j ] = !( matches[ j ] = seed[ j ] );
					}
				}
			} );
		} );
	}

	/**
	 * Checks a node for validity as a jQuery selector context
	 * @param {Element|Object=} context
	 * @returns {Element|Object|Boolean} The input node if acceptable, otherwise a falsy value
	 */
	function testContext( context ) {
		return context && typeof context.getElementsByTagName !== "undefined" && context;
	}

	/**
	 * Sets document-related variables once based on the current document
	 * @param {Element|Object} [node] An element or document object to use to set the document
	 * @returns {Object} Returns the current document
	 */
	function setDocument( node ) {
		var subWindow,
			doc = node ? node.ownerDocument || node : preferredDoc;

		// Return early if doc is invalid or already selected
		// Support: IE 11+, Edge 17 - 18+
		// IE/Edge sometimes throw a "Permission denied" error when strict-comparing
		// two documents; shallow comparisons work.
		// eslint-disable-next-line eqeqeq
		if ( doc == document || doc.nodeType !== 9 || !doc.documentElement ) {
			return document;
		}

		// Update global variables
		document = doc;
		documentElement = document.documentElement;
		documentIsHTML = !jQuery.isXMLDoc( document );

		// Support: iOS 7 only, IE 9 - 11+
		// Older browsers didn't support unprefixed `matches`.
		matches = documentElement.matches ||
			documentElement.webkitMatchesSelector ||
			documentElement.msMatchesSelector;

		// Support: IE 9 - 11+, Edge 12 - 18+
		// Accessing iframe documents after unload throws "permission denied" errors
		// (see trac-13936).
		// Limit the fix to IE & Edge Legacy; despite Edge 15+ implementing `matches`,
		// all IE 9+ and Edge Legacy versions implement `msMatchesSelector` as well.
		if ( documentElement.msMatchesSelector &&

			// Support: IE 11+, Edge 17 - 18+
			// IE/Edge sometimes throw a "Permission denied" error when strict-comparing
			// two documents; shallow comparisons work.
			// eslint-disable-next-line eqeqeq
			preferredDoc != document &&
			( subWindow = document.defaultView ) && subWindow.top !== subWindow ) {

			// Support: IE 9 - 11+, Edge 12 - 18+
			subWindow.addEventListener( "unload", unloadHandler );
		}

		// Support: IE <10
		// Check if getElementById returns elements by name
		// The broken getElementById methods don't pick up programmatically-set names,
		// so use a roundabout getElementsByName test
		support.getById = assert( function( el ) {
			documentElement.appendChild( el ).id = jQuery.expando;
			return !document.getElementsByName ||
				!document.getElementsByName( jQuery.expando ).length;
		} );

		// Support: IE 9 only
		// Check to see if it's possible to do matchesSelector
		// on a disconnected node.
		support.disconnectedMatch = assert( function( el ) {
			return matches.call( el, "*" );
		} );

		// Support: IE 9 - 11+, Edge 12 - 18+
		// IE/Edge don't support the :scope pseudo-class.
		support.scope = assert( function() {
			return document.querySelectorAll( ":scope" );
		} );

		// Support: Chrome 105 - 111 only, Safari 15.4 - 16.3 only
		// Make sure the `:has()` argument is parsed unforgivingly.
		// We include `*` in the test to detect buggy implementations that are
		// _selectively_ forgiving (specifically when the list includes at least
		// one valid selector).
		// Note that we treat complete lack of support for `:has()` as if it were
		// spec-compliant support, which is fine because use of `:has()` in such
		// environments will fail in the qSA path and fall back to jQuery traversal
		// anyway.
		support.cssHas = assert( function() {
			try {
				document.querySelector( ":has(*,:jqfake)" );
				return false;
			} catch ( e ) {
				return true;
			}
		} );

		// ID filter and find
		if ( support.getById ) {
			Expr.filter.ID = function( id ) {
				var attrId = id.replace( runescape, funescape );
				return function( elem ) {
					return elem.getAttribute( "id" ) === attrId;
				};
			};
			Expr.find.ID = function( id, context ) {
				if ( typeof context.getElementById !== "undefined" && documentIsHTML ) {
					var elem = context.getElementById( id );
					return elem ? [ elem ] : [];
				}
			};
		} else {
			Expr.filter.ID =  function( id ) {
				var attrId = id.replace( runescape, funescape );
				return function( elem ) {
					var node = typeof elem.getAttributeNode !== "undefined" &&
						elem.getAttributeNode( "id" );
					return node && node.value === attrId;
				};
			};

			// Support: IE 6 - 7 only
			// getElementById is not reliable as a find shortcut
			Expr.find.ID = function( id, context ) {
				if ( typeof context.getElementById !== "undefined" && documentIsHTML ) {
					var node, i, elems,
						elem = context.getElementById( id );

					if ( elem ) {

						// Verify the id attribute
						node = elem.getAttributeNode( "id" );
						if ( node && node.value === id ) {
							return [ elem ];
						}

						// Fall back on getElementsByName
						elems = context.getElementsByName( id );
						i = 0;
						while ( ( elem = elems[ i++ ] ) ) {
							node = elem.getAttributeNode( "id" );
							if ( node && node.value === id ) {
								return [ elem ];
							}
						}
					}

					return [];
				}
			};
		}

		// Tag
		Expr.find.TAG = function( tag, context ) {
			if ( typeof context.getElementsByTagName !== "undefined" ) {
				return context.getElementsByTagName( tag );

			// DocumentFragment nodes don't have gEBTN
			} else {
				return context.querySelectorAll( tag );
			}
		};

		// Class
		Expr.find.CLASS = function( className, context ) {
			if ( typeof context.getElementsByClassName !== "undefined" && documentIsHTML ) {
				return context.getElementsByClassName( className );
			}
		};

		/* QSA/matchesSelector
		---------------------------------------------------------------------- */

		// QSA and matchesSelector support

		rbuggyQSA = [];

		// Build QSA regex
		// Regex strategy adopted from Diego Perini
		assert( function( el ) {

			var input;

			documentElement.appendChild( el ).innerHTML =
				"<a id='" + expando + "' href='' disabled='disabled'></a>" +
				"<select id='" + expando + "-\r\\' disabled='disabled'>" +
				"<option selected=''></option></select>";

			// Support: iOS <=7 - 8 only
			// Boolean attributes and "value" are not treated correctly in some XML documents
			if ( !el.querySelectorAll( "[selected]" ).length ) {
				rbuggyQSA.push( "\\[" + whitespace + "*(?:value|" + booleans + ")" );
			}

			// Support: iOS <=7 - 8 only
			if ( !el.querySelectorAll( "[id~=" + expando + "-]" ).length ) {
				rbuggyQSA.push( "~=" );
			}

			// Support: iOS 8 only
			// https://bugs.webkit.org/show_bug.cgi?id=136851
			// In-page `selector#id sibling-combinator selector` fails
			if ( !el.querySelectorAll( "a#" + expando + "+*" ).length ) {
				rbuggyQSA.push( ".#.+[+~]" );
			}

			// Support: Chrome <=105+, Firefox <=104+, Safari <=15.4+
			// In some of the document kinds, these selectors wouldn't work natively.
			// This is probably OK but for backwards compatibility we want to maintain
			// handling them through jQuery traversal in jQuery 3.x.
			if ( !el.querySelectorAll( ":checked" ).length ) {
				rbuggyQSA.push( ":checked" );
			}

			// Support: Windows 8 Native Apps
			// The type and name attributes are restricted during .innerHTML assignment
			input = document.createElement( "input" );
			input.setAttribute( "type", "hidden" );
			el.appendChild( input ).setAttribute( "name", "D" );

			// Support: IE 9 - 11+
			// IE's :disabled selector does not pick up the children of disabled fieldsets
			// Support: Chrome <=105+, Firefox <=104+, Safari <=15.4+
			// In some of the document kinds, these selectors wouldn't work natively.
			// This is probably OK but for backwards compatibility we want to maintain
			// handling them through jQuery traversal in jQuery 3.x.
			documentElement.appendChild( el ).disabled = true;
			if ( el.querySelectorAll( ":disabled" ).length !== 2 ) {
				rbuggyQSA.push( ":enabled", ":disabled" );
			}

			// Support: IE 11+, Edge 15 - 18+
			// IE 11/Edge don't find elements on a `[name='']` query in some cases.
			// Adding a temporary attribute to the document before the selection works
			// around the issue.
			// Interestingly, IE 10 & older don't seem to have the issue.
			input = document.createElement( "input" );
			input.setAttribute( "name", "" );
			el.appendChild( input );
			if ( !el.querySelectorAll( "[name='']" ).length ) {
				rbuggyQSA.push( "\\[" + whitespace + "*name" + whitespace + "*=" +
					whitespace + "*(?:''|\"\")" );
			}
		} );

		if ( !support.cssHas ) {

			// Support: Chrome 105 - 110+, Safari 15.4 - 16.3+
			// Our regular `try-catch` mechanism fails to detect natively-unsupported
			// pseudo-classes inside `:has()` (such as `:has(:contains("Foo"))`)
			// in browsers that parse the `:has()` argument as a forgiving selector list.
			// https://drafts.csswg.org/selectors/#relational now requires the argument
			// to be parsed unforgivingly, but browsers have not yet fully adjusted.
			rbuggyQSA.push( ":has" );
		}

		rbuggyQSA = rbuggyQSA.length && new RegExp( rbuggyQSA.join( "|" ) );

		/* Sorting
		---------------------------------------------------------------------- */

		// Document order sorting
		sortOrder = function( a, b ) {

			// Flag for duplicate removal
			if ( a === b ) {
				hasDuplicate = true;
				return 0;
			}

			// Sort on method existence if only one input has compareDocumentPosition
			var compare = !a.compareDocumentPosition - !b.compareDocumentPosition;
			if ( compare ) {
				return compare;
			}

			// Calculate position if both inputs belong to the same document
			// Support: IE 11+, Edge 17 - 18+
			// IE/Edge sometimes throw a "Permission denied" error when strict-comparing
			// two documents; shallow comparisons work.
			// eslint-disable-next-line eqeqeq
			compare = ( a.ownerDocument || a ) == ( b.ownerDocument || b ) ?
				a.compareDocumentPosition( b ) :

				// Otherwise we know they are disconnected
				1;

			// Disconnected nodes
			if ( compare & 1 ||
				( !support.sortDetached && b.compareDocumentPosition( a ) === compare ) ) {

				// Choose the first element that is related to our preferred document
				// Support: IE 11+, Edge 17 - 18+
				// IE/Edge sometimes throw a "Permission denied" error when strict-comparing
				// two documents; shallow comparisons work.
				// eslint-disable-next-line eqeqeq
				if ( a === document || a.ownerDocument == preferredDoc &&
					find.contains( preferredDoc, a ) ) {
					return -1;
				}

				// Support: IE 11+, Edge 17 - 18+
				// IE/Edge sometimes throw a "Permission denied" error when strict-comparing
				// two documents; shallow comparisons work.
				// eslint-disable-next-line eqeqeq
				if ( b === document || b.ownerDocument == preferredDoc &&
					find.contains( preferredDoc, b ) ) {
					return 1;
				}

				// Maintain original order
				return sortInput ?
					( indexOf.call( sortInput, a ) - indexOf.call( sortInput, b ) ) :
					0;
			}

			return compare & 4 ? -1 : 1;
		};

		return document;
	}

	find.matches = function( expr, elements ) {
		return find( expr, null, null, elements );
	};

	find.matchesSelector = function( elem, expr ) {
		setDocument( elem );

		if ( documentIsHTML &&
			!nonnativeSelectorCache[ expr + " " ] &&
			( !rbuggyQSA || !rbuggyQSA.test( expr ) ) ) {

			try {
				var ret = matches.call( elem, expr );

				// IE 9's matchesSelector returns false on disconnected nodes
				if ( ret || support.disconnectedMatch ||

						// As well, disconnected nodes are said to be in a document
						// fragment in IE 9
						elem.document && elem.document.nodeType !== 11 ) {
					return ret;
				}
			} catch ( e ) {
				nonnativeSelectorCache( expr, true );
			}
		}

		return find( expr, document, null, [ elem ] ).length > 0;
	};

	find.contains = function( context, elem ) {

		// Set document vars if needed
		// Support: IE 11+, Edge 17 - 18+
		// IE/Edge sometimes throw a "Permission denied" error when strict-comparing
		// two documents; shallow comparisons work.
		// eslint-disable-next-line eqeqeq
		if ( ( context.ownerDocument || context ) != document ) {
			setDocument( context );
		}
		return jQuery.contains( context, elem );
	};


	find.attr = function( elem, name ) {

		// Set document vars if needed
		// Support: IE 11+, Edge 17 - 18+
		// IE/Edge sometimes throw a "Permission denied" error when strict-comparing
		// two documents; shallow comparisons work.
		// eslint-disable-next-line eqeqeq
		if ( ( elem.ownerDocument || elem ) != document ) {
			setDocument( elem );
		}

		var fn = Expr.attrHandle[ name.toLowerCase() ],

			// Don't get fooled by Object.prototype properties (see trac-13807)
			val = fn && hasOwn.call( Expr.attrHandle, name.toLowerCase() ) ?
				fn( elem, name, !documentIsHTML ) :
				undefined;

		if ( val !== undefined ) {
			return val;
		}

		return elem.getAttribute( name );
	};

	find.error = function( msg ) {
		throw new Error( "Syntax error, unrecognized expression: " + msg );
	};

	/**
	 * Document sorting and removing duplicates
	 * @param {ArrayLike} results
	 */
	jQuery.uniqueSort = function( results ) {
		var elem,
			duplicates = [],
			j = 0,
			i = 0;

		// Unless we *know* we can detect duplicates, assume their presence
		//
		// Support: Android <=4.0+
		// Testing for detecting duplicates is unpredictable so instead assume we can't
		// depend on duplicate detection in all browsers without a stable sort.
		hasDuplicate = !support.sortStable;
		sortInput = !support.sortStable && slice.call( results, 0 );
		sort.call( results, sortOrder );

		if ( hasDuplicate ) {
			while ( ( elem = results[ i++ ] ) ) {
				if ( elem === results[ i ] ) {
					j = duplicates.push( i );
				}
			}
			while ( j-- ) {
				splice.call( results, duplicates[ j ], 1 );
			}
		}

		// Clear input after sorting to release objects
		// See https://github.com/jquery/sizzle/pull/225
		sortInput = null;

		return results;
	};

	jQuery.fn.uniqueSort = function() {
		return this.pushStack( jQuery.uniqueSort( slice.apply( this ) ) );
	};

	Expr = jQuery.expr = {

		// Can be adjusted by the user
		cacheLength: 50,

		createPseudo: markFunction,

		match: matchExpr,

		attrHandle: {},

		find: {},

		relative: {
			">": { dir: "parentNode", first: true },
			" ": { dir: "parentNode" },
			"+": { dir: "previousSibling", first: true },
			"~": { dir: "previousSibling" }
		},

		preFilter: {
			ATTR: function( match ) {
				match[ 1 ] = match[ 1 ].replace( runescape, funescape );

				// Move the given value to match[3] whether quoted or unquoted
				match[ 3 ] = ( match[ 3 ] || match[ 4 ] || match[ 5 ] || "" )
					.replace( runescape, funescape );

				if ( match[ 2 ] === "~=" ) {
					match[ 3 ] = " " + match[ 3 ] + " ";
				}

				return match.slice( 0, 4 );
			},

			CHILD: function( match ) {

				/* matches from matchExpr["CHILD"]
					1 type (only|nth|...)
					2 what (child|of-type)
					3 argument (even|odd|\d*|\d*n([+-]\d+)?|...)
					4 xn-component of xn+y argument ([+-]?\d*n|)
					5 sign of xn-component
					6 x of xn-component
					7 sign of y-component
					8 y of y-component
				*/
				match[ 1 ] = match[ 1 ].toLowerCase();

				if ( match[ 1 ].slice( 0, 3 ) === "nth" ) {

					// nth-* requires argument
					if ( !match[ 3 ] ) {
						find.error( match[ 0 ] );
					}

					// numeric x and y parameters for Expr.filter.CHILD
					// remember that false/true cast respectively to 0/1
					match[ 4 ] = +( match[ 4 ] ?
						match[ 5 ] + ( match[ 6 ] || 1 ) :
						2 * ( match[ 3 ] === "even" || match[ 3 ] === "odd" )
					);
					match[ 5 ] = +( ( match[ 7 ] + match[ 8 ] ) || match[ 3 ] === "odd" );

				// other types prohibit arguments
				} else if ( match[ 3 ] ) {
					find.error( match[ 0 ] );
				}

				return match;
			},

			PSEUDO: function( match ) {
				var excess,
					unquoted = !match[ 6 ] && match[ 2 ];

				if ( matchExpr.CHILD.test( match[ 0 ] ) ) {
					return null;
				}

				// Accept quoted arguments as-is
				if ( match[ 3 ] ) {
					match[ 2 ] = match[ 4 ] || match[ 5 ] || "";

				// Strip excess characters from unquoted arguments
				} else if ( unquoted && rpseudo.test( unquoted ) &&

					// Get excess from tokenize (recursively)
					( excess = tokenize( unquoted, true ) ) &&

					// advance to the next closing parenthesis
					( excess = unquoted.indexOf( ")", unquoted.length - excess ) - unquoted.length ) ) {

					// excess is a negative index
					match[ 0 ] = match[ 0 ].slice( 0, excess );
					match[ 2 ] = unquoted.slice( 0, excess );
				}

				// Return only captures needed by the pseudo filter method (type and argument)
				return match.slice( 0, 3 );
			}
		},

		filter: {

			TAG: function( nodeNameSelector ) {
				var expectedNodeName = nodeNameSelector.replace( runescape, funescape ).toLowerCase();
				return nodeNameSelector === "*" ?
					function() {
						return true;
					} :
					function( elem ) {
						return nodeName( elem, expectedNodeName );
					};
			},

			CLASS: function( className ) {
				var pattern = classCache[ className + " " ];

				return pattern ||
					( pattern = new RegExp( "(^|" + whitespace + ")" + className +
						"(" + whitespace + "|$)" ) ) &&
					classCache( className, function( elem ) {
						return pattern.test(
							typeof elem.className === "string" && elem.className ||
								typeof elem.getAttribute !== "undefined" &&
									elem.getAttribute( "class" ) ||
								""
						);
					} );
			},

			ATTR: function( name, operator, check ) {
				return function( elem ) {
					var result = find.attr( elem, name );

					if ( result == null ) {
						return operator === "!=";
					}
					if ( !operator ) {
						return true;
					}

					result += "";

					if ( operator === "=" ) {
						return result === check;
					}
					if ( operator === "!=" ) {
						return result !== check;
					}
					if ( operator === "^=" ) {
						return check && result.indexOf( check ) === 0;
					}
					if ( operator === "*=" ) {
						return check && result.indexOf( check ) > -1;
					}
					if ( operator === "$=" ) {
						return check && result.slice( -check.length ) === check;
					}
					if ( operator === "~=" ) {
						return ( " " + result.replace( rwhitespace, " " ) + " " )
							.indexOf( check ) > -1;
					}
					if ( operator === "|=" ) {
						return result === check || result.slice( 0, check.length + 1 ) === check + "-";
					}

					return false;
				};
			},

			CHILD: function( type, what, _argument, first, last ) {
				var simple = type.slice( 0, 3 ) !== "nth",
					forward = type.slice( -4 ) !== "last",
					ofType = what === "of-type";

				return first === 1 && last === 0 ?

					// Shortcut for :nth-*(n)
					function( elem ) {
						return !!elem.parentNode;
					} :

					function( elem, _context, xml ) {
						var cache, outerCache, node, nodeIndex, start,
							dir = simple !== forward ? "nextSibling" : "previousSibling",
							parent = elem.parentNode,
							name = ofType && elem.nodeName.toLowerCase(),
							useCache = !xml && !ofType,
							diff = false;

						if ( parent ) {

							// :(first|last|only)-(child|of-type)
							if ( simple ) {
								while ( dir ) {
									node = elem;
									while ( ( node = node[ dir ] ) ) {
										if ( ofType ?
											nodeName( node, name ) :
											node.nodeType === 1 ) {

											return false;
										}
									}

									// Reverse direction for :only-* (if we haven't yet done so)
									start = dir = type === "only" && !start && "nextSibling";
								}
								return true;
							}

							start = [ forward ? parent.firstChild : parent.lastChild ];

							// non-xml :nth-child(...) stores cache data on `parent`
							if ( forward && useCache ) {

								// Seek `elem` from a previously-cached index
								outerCache = parent[ expando ] || ( parent[ expando ] = {} );
								cache = outerCache[ type ] || [];
								nodeIndex = cache[ 0 ] === dirruns && cache[ 1 ];
								diff = nodeIndex && cache[ 2 ];
								node = nodeIndex && parent.childNodes[ nodeIndex ];

								while ( ( node = ++nodeIndex && node && node[ dir ] ||

									// Fallback to seeking `elem` from the start
									( diff = nodeIndex = 0 ) || start.pop() ) ) {

									// When found, cache indexes on `parent` and break
									if ( node.nodeType === 1 && ++diff && node === elem ) {
										outerCache[ type ] = [ dirruns, nodeIndex, diff ];
										break;
									}
								}

							} else {

								// Use previously-cached element index if available
								if ( useCache ) {
									outerCache = elem[ expando ] || ( elem[ expando ] = {} );
									cache = outerCache[ type ] || [];
									nodeIndex = cache[ 0 ] === dirruns && cache[ 1 ];
									diff = nodeIndex;
								}

								// xml :nth-child(...)
								// or :nth-last-child(...) or :nth(-last)?-of-type(...)
								if ( diff === false ) {

									// Use the same loop as above to seek `elem` from the start
									while ( ( node = ++nodeIndex && node && node[ dir ] ||
										( diff = nodeIndex = 0 ) || start.pop() ) ) {

										if ( ( ofType ?
											nodeName( node, name ) :
											node.nodeType === 1 ) &&
											++diff ) {

											// Cache the index of each encountered element
											if ( useCache ) {
												outerCache = node[ expando ] ||
													( node[ expando ] = {} );
												outerCache[ type ] = [ dirruns, diff ];
											}

											if ( node === elem ) {
												break;
											}
										}
									}
								}
							}

							// Incorporate the offset, then check against cycle size
							diff -= last;
							return diff === first || ( diff % first === 0 && diff / first >= 0 );
						}
					};
			},

			PSEUDO: function( pseudo, argument ) {

				// pseudo-class names are case-insensitive
				// https://www.w3.org/TR/selectors/#pseudo-classes
				// Prioritize by case sensitivity in case custom pseudos are added with uppercase letters
				// Remember that setFilters inherits from pseudos
				var args,
					fn = Expr.pseudos[ pseudo ] || Expr.setFilters[ pseudo.toLowerCase() ] ||
						find.error( "unsupported pseudo: " + pseudo );

				// The user may use createPseudo to indicate that
				// arguments are needed to create the filter function
				// just as jQuery does
				if ( fn[ expando ] ) {
					return fn( argument );
				}

				// But maintain support for old signatures
				if ( fn.length > 1 ) {
					args = [ pseudo, pseudo, "", argument ];
					return Expr.setFilters.hasOwnProperty( pseudo.toLowerCase() ) ?
						markFunction( function( seed, matches ) {
							var idx,
								matched = fn( seed, argument ),
								i = matched.length;
							while ( i-- ) {
								idx = indexOf.call( seed, matched[ i ] );
								seed[ idx ] = !( matches[ idx ] = matched[ i ] );
							}
						} ) :
						function( elem ) {
							return fn( elem, 0, args );
						};
				}

				return fn;
			}
		},

		pseudos: {

			// Potentially complex pseudos
			not: markFunction( function( selector ) {

				// Trim the selector passed to compile
				// to avoid treating leading and trailing
				// spaces as combinators
				var input = [],
					results = [],
					matcher = compile( selector.replace( rtrimCSS, "$1" ) );

				return matcher[ expando ] ?
					markFunction( function( seed, matches, _context, xml ) {
						var elem,
							unmatched = matcher( seed, null, xml, [] ),
							i = seed.length;

						// Match elements unmatched by `matcher`
						while ( i-- ) {
							if ( ( elem = unmatched[ i ] ) ) {
								seed[ i ] = !( matches[ i ] = elem );
							}
						}
					} ) :
					function( elem, _context, xml ) {
						input[ 0 ] = elem;
						matcher( input, null, xml, results );

						// Don't keep the element
						// (see https://github.com/jquery/sizzle/issues/299)
						input[ 0 ] = null;
						return !results.pop();
					};
			} ),

			has: markFunction( function( selector ) {
				return function( elem ) {
					return find( selector, elem ).length > 0;
				};
			} ),

			contains: markFunction( function( text ) {
				text = text.replace( runescape, funescape );
				return function( elem ) {
					return ( elem.textContent || jQuery.text( elem ) ).indexOf( text ) > -1;
				};
			} ),

			// "Whether an element is represented by a :lang() selector
			// is based solely on the element's language value
			// being equal to the identifier C,
			// or beginning with the identifier C immediately followed by "-".
			// The matching of C against the element's language value is performed case-insensitively.
			// The identifier C does not have to be a valid language name."
			// https://www.w3.org/TR/selectors/#lang-pseudo
			lang: markFunction( function( lang ) {

				// lang value must be a valid identifier
				if ( !ridentifier.test( lang || "" ) ) {
					find.error( "unsupported lang: " + lang );
				}
				lang = lang.replace( runescape, funescape ).toLowerCase();
				return function( elem ) {
					var elemLang;
					do {
						if ( ( elemLang = documentIsHTML ?
							elem.lang :
							elem.getAttribute( "xml:lang" ) || elem.getAttribute( "lang" ) ) ) {

							elemLang = elemLang.toLowerCase();
							return elemLang === lang || elemLang.indexOf( lang + "-" ) === 0;
						}
					} while ( ( elem = elem.parentNode ) && elem.nodeType === 1 );
					return false;
				};
			} ),

			// Miscellaneous
			target: function( elem ) {
				var hash = window.location && window.location.hash;
				return hash && hash.slice( 1 ) === elem.id;
			},

			root: function( elem ) {
				return elem === documentElement;
			},

			focus: function( elem ) {
				return elem === safeActiveElement() &&
					document.hasFocus() &&
					!!( elem.type || elem.href || ~elem.tabIndex );
			},

			// Boolean properties
			enabled: createDisabledPseudo( false ),
			disabled: createDisabledPseudo( true ),

			checked: function( elem ) {

				// In CSS3, :checked should return both checked and selected elements
				// https://www.w3.org/TR/2011/REC-css3-selectors-20110929/#checked
				return ( nodeName( elem, "input" ) && !!elem.checked ) ||
					( nodeName( elem, "option" ) && !!elem.selected );
			},

			selected: function( elem ) {

				// Support: IE <=11+
				// Accessing the selectedIndex property
				// forces the browser to treat the default option as
				// selected when in an optgroup.
				if ( elem.parentNode ) {
					// eslint-disable-next-line no-unused-expressions
					elem.parentNode.selectedIndex;
				}

				return elem.selected === true;
			},

			// Contents
			empty: function( elem ) {

				// https://www.w3.org/TR/selectors/#empty-pseudo
				// :empty is negated by element (1) or content nodes (text: 3; cdata: 4; entity ref: 5),
				//   but not by others (comment: 8; processing instruction: 7; etc.)
				// nodeType < 6 works because attributes (2) do not appear as children
				for ( elem = elem.firstChild; elem; elem = elem.nextSibling ) {
					if ( elem.nodeType < 6 ) {
						return false;
					}
				}
				return true;
			},

			parent: function( elem ) {
				return !Expr.pseudos.empty( elem );
			},

			// Element/input types
			header: function( elem ) {
				return rheader.test( elem.nodeName );
			},

			input: function( elem ) {
				return rinputs.test( elem.nodeName );
			},

			button: function( elem ) {
				return nodeName( elem, "input" ) && elem.type === "button" ||
					nodeName( elem, "button" );
			},

			text: function( elem ) {
				var attr;
				return nodeName( elem, "input" ) && elem.type === "text" &&

					// Support: IE <10 only
					// New HTML5 attribute values (e.g., "search") appear
					// with elem.type === "text"
					( ( attr = elem.getAttribute( "type" ) ) == null ||
						attr.toLowerCase() === "text" );
			},

			// Position-in-collection
			first: createPositionalPseudo( function() {
				return [ 0 ];
			} ),

			last: createPositionalPseudo( function( _matchIndexes, length ) {
				return [ length - 1 ];
			} ),

			eq: createPositionalPseudo( function( _matchIndexes, length, argument ) {
				return [ argument < 0 ? argument + length : argument ];
			} ),

			even: createPositionalPseudo( function( matchIndexes, length ) {
				var i = 0;
				for ( ; i < length; i += 2 ) {
					matchIndexes.push( i );
				}
				return matchIndexes;
			} ),

			odd: createPositionalPseudo( function( matchIndexes, length ) {
				var i = 1;
				for ( ; i < length; i += 2 ) {
					matchIndexes.push( i );
				}
				return matchIndexes;
			} ),

			lt: createPositionalPseudo( function( matchIndexes, length, argument ) {
				var i;

				if ( argument < 0 ) {
					i = argument + length;
				} else if ( argument > length ) {
					i = length;
				} else {
					i = argument;
				}

				for ( ; --i >= 0; ) {
					matchIndexes.push( i );
				}
				return matchIndexes;
			} ),

			gt: createPositionalPseudo( function( matchIndexes, length, argument ) {
				var i = argument < 0 ? argument + length : argument;
				for ( ; ++i < length; ) {
					matchIndexes.push( i );
				}
				return matchIndexes;
			} )
		}
	};

	Expr.pseudos.nth = Expr.pseudos.eq;

	// Add button/input type pseudos
	for ( i in { radio: true, checkbox: true, file: true, password: true, image: true } ) {
		Expr.pseudos[ i ] = createInputPseudo( i );
	}
	for ( i in { submit: true, reset: true } ) {
		Expr.pseudos[ i ] = createButtonPseudo( i );
	}

	// Easy API for creating new setFilters
	function setFilters() {}
	setFilters.prototype = Expr.filters = Expr.pseudos;
	Expr.setFilters = new setFilters();

	function tokenize( selector, parseOnly ) {
		var matched, match, tokens, type,
			soFar, groups, preFilters,
			cached = tokenCache[ selector + " " ];

		if ( cached ) {
			return parseOnly ? 0 : cached.slice( 0 );
		}

		soFar = selector;
		groups = [];
		preFilters = Expr.preFilter;

		while ( soFar ) {

			// Comma and first run
			if ( !matched || ( match = rcomma.exec( soFar ) ) ) {
				if ( match ) {

					// Don't consume trailing commas as valid
					soFar = soFar.slice( match[ 0 ].length ) || soFar;
				}
				groups.push( ( tokens = [] ) );
			}

			matched = false;

			// Combinators
			if ( ( match = rleadingCombinator.exec( soFar ) ) ) {
				matched = match.shift();
				tokens.push( {
					value: matched,

					// Cast descendant combinators to space
					type: match[ 0 ].replace( rtrimCSS, " " )
				} );
				soFar = soFar.slice( matched.length );
			}

			// Filters
			for ( type in Expr.filter ) {
				if ( ( match = matchExpr[ type ].exec( soFar ) ) && ( !preFilters[ type ] ||
					( match = preFilters[ type ]( match ) ) ) ) {
					matched = match.shift();
					tokens.push( {
						value: matched,
						type: type,
						matches: match
					} );
					soFar = soFar.slice( matched.length );
				}
			}

			if ( !matched ) {
				break;
			}
		}

		// Return the length of the invalid excess
		// if we're just parsing
		// Otherwise, throw an error or return tokens
		if ( parseOnly ) {
			return soFar.length;
		}

		return soFar ?
			find.error( selector ) :

			// Cache the tokens
			tokenCache( selector, groups ).slice( 0 );
	}

	function toSelector( tokens ) {
		var i = 0,
			len = tokens.length,
			selector = "";
		for ( ; i < len; i++ ) {
			selector += tokens[ i ].value;
		}
		return selector;
	}

	function addCombinator( matcher, combinator, base ) {
		var dir = combinator.dir,
			skip = combinator.next,
			key = skip || dir,
			checkNonElements = base && key === "parentNode",
			doneName = done++;

		return combinator.first ?

			// Check against closest ancestor/preceding element
			function( elem, context, xml ) {
				while ( ( elem = elem[ dir ] ) ) {
					if ( elem.nodeType === 1 || checkNonElements ) {
						return matcher( elem, context, xml );
					}
				}
				return false;
			} :

			// Check against all ancestor/preceding elements
			function( elem, context, xml ) {
				var oldCache, outerCache,
					newCache = [ dirruns, doneName ];

				// We can't set arbitrary data on XML nodes, so they don't benefit from combinator caching
				if ( xml ) {
					while ( ( elem = elem[ dir ] ) ) {
						if ( elem.nodeType === 1 || checkNonElements ) {
							if ( matcher( elem, context, xml ) ) {
								return true;
							}
						}
					}
				} else {
					while ( ( elem = elem[ dir ] ) ) {
						if ( elem.nodeType === 1 || checkNonElements ) {
							outerCache = elem[ expando ] || ( elem[ expando ] = {} );

							if ( skip && nodeName( elem, skip ) ) {
								elem = elem[ dir ] || elem;
							} else if ( ( oldCache = outerCache[ key ] ) &&
								oldCache[ 0 ] === dirruns && oldCache[ 1 ] === doneName ) {

								// Assign to newCache so results back-propagate to previous elements
								return ( newCache[ 2 ] = oldCache[ 2 ] );
							} else {

								// Reuse newcache so results back-propagate to previous elements
								outerCache[ key ] = newCache;

								// A match means we're done; a fail means we have to keep checking
								if ( ( newCache[ 2 ] = matcher( elem, context, xml ) ) ) {
									return true;
								}
							}
						}
					}
				}
				return false;
			};
	}

	function elementMatcher( matchers ) {
		return matchers.length > 1 ?
			function( elem, context, xml ) {
				var i = matchers.length;
				while ( i-- ) {
					if ( !matchers[ i ]( elem, context, xml ) ) {
						return false;
					}
				}
				return true;
			} :
			matchers[ 0 ];
	}

	function multipleContexts( selector, contexts, results ) {
		var i = 0,
			len = contexts.length;
		for ( ; i < len; i++ ) {
			find( selector, contexts[ i ], results );
		}
		return results;
	}

	function condense( unmatched, map, filter, context, xml ) {
		var elem,
			newUnmatched = [],
			i = 0,
			len = unmatched.length,
			mapped = map != null;

		for ( ; i < len; i++ ) {
			if ( ( elem = unmatched[ i ] ) ) {
				if ( !filter || filter( elem, context, xml ) ) {
					newUnmatched.push( elem );
					if ( mapped ) {
						map.push( i );
					}
				}
			}
		}

		return newUnmatched;
	}

	function setMatcher( preFilter, selector, matcher, postFilter, postFinder, postSelector ) {
		if ( postFilter && !postFilter[ expando ] ) {
			postFilter = setMatcher( postFilter );
		}
		if ( postFinder && !postFinder[ expando ] ) {
			postFinder = setMatcher( postFinder, postSelector );
		}
		return markFunction( function( seed, results, context, xml ) {
			var temp, i, elem, matcherOut,
				preMap = [],
				postMap = [],
				preexisting = results.length,

				// Get initial elements from seed or context
				elems = seed ||
					multipleContexts( selector || "*",
						context.nodeType ? [ context ] : context, [] ),

				// Prefilter to get matcher input, preserving a map for seed-results synchronization
				matcherIn = preFilter && ( seed || !selector ) ?
					condense( elems, preMap, preFilter, context, xml ) :
					elems;

			if ( matcher ) {

				// If we have a postFinder, or filtered seed, or non-seed postFilter
				// or preexisting results,
				matcherOut = postFinder || ( seed ? preFilter : preexisting || postFilter ) ?

					// ...intermediate processing is necessary
					[] :

					// ...otherwise use results directly
					results;

				// Find primary matches
				matcher( matcherIn, matcherOut, context, xml );
			} else {
				matcherOut = matcherIn;
			}

			// Apply postFilter
			if ( postFilter ) {
				temp = condense( matcherOut, postMap );
				postFilter( temp, [], context, xml );

				// Un-match failing elements by moving them back to matcherIn
				i = temp.length;
				while ( i-- ) {
					if ( ( elem = temp[ i ] ) ) {
						matcherOut[ postMap[ i ] ] = !( matcherIn[ postMap[ i ] ] = elem );
					}
				}
			}

			if ( seed ) {
				if ( postFinder || preFilter ) {
					if ( postFinder ) {

						// Get the final matcherOut by condensing this intermediate into postFinder contexts
						temp = [];
						i = matcherOut.length;
						while ( i-- ) {
							if ( ( elem = matcherOut[ i ] ) ) {

								// Restore matcherIn since elem is not yet a final match
								temp.push( ( matcherIn[ i ] = elem ) );
							}
						}
						postFinder( null, ( matcherOut = [] ), temp, xml );
					}

					// Move matched elements from seed to results to keep them synchronized
					i = matcherOut.length;
					while ( i-- ) {
						if ( ( elem = matcherOut[ i ] ) &&
							( temp = postFinder ? indexOf.call( seed, elem ) : preMap[ i ] ) > -1 ) {

							seed[ temp ] = !( results[ temp ] = elem );
						}
					}
				}

			// Add elements to results, through postFinder if defined
			} else {
				matcherOut = condense(
					matcherOut === results ?
						matcherOut.splice( preexisting, matcherOut.length ) :
						matcherOut
				);
				if ( postFinder ) {
					postFinder( null, results, matcherOut, xml );
				} else {
					push.apply( results, matcherOut );
				}
			}
		} );
	}

	function matcherFromTokens( tokens ) {
		var checkContext, matcher, j,
			len = tokens.length,
			leadingRelative = Expr.relative[ tokens[ 0 ].type ],
			implicitRelative = leadingRelative || Expr.relative[ " " ],
			i = leadingRelative ? 1 : 0,

			// The foundational matcher ensures that elements are reachable from top-level context(s)
			matchContext = addCombinator( function( elem ) {
				return elem === checkContext;
			}, implicitRelative, true ),
			matchAnyContext = addCombinator( function( elem ) {
				return indexOf.call( checkContext, elem ) > -1;
			}, implicitRelative, true ),
			matchers = [ function( elem, context, xml ) {

				// Support: IE 11+, Edge 17 - 18+
				// IE/Edge sometimes throw a "Permission denied" error when strict-comparing
				// two documents; shallow comparisons work.
				// eslint-disable-next-line eqeqeq
				var ret = ( !leadingRelative && ( xml || context != outermostContext ) ) || (
					( checkContext = context ).nodeType ?
						matchContext( elem, context, xml ) :
						matchAnyContext( elem, context, xml ) );

				// Avoid hanging onto element
				// (see https://github.com/jquery/sizzle/issues/299)
				checkContext = null;
				return ret;
			} ];

		for ( ; i < len; i++ ) {
			if ( ( matcher = Expr.relative[ tokens[ i ].type ] ) ) {
				matchers = [ addCombinator( elementMatcher( matchers ), matcher ) ];
			} else {
				matcher = Expr.filter[ tokens[ i ].type ].apply( null, tokens[ i ].matches );

				// Return special upon seeing a positional matcher
				if ( matcher[ expando ] ) {

					// Find the next relative operator (if any) for proper handling
					j = ++i;
					for ( ; j < len; j++ ) {
						if ( Expr.relative[ tokens[ j ].type ] ) {
							break;
						}
					}
					return setMatcher(
						i > 1 && elementMatcher( matchers ),
						i > 1 && toSelector(

							// If the preceding token was a descendant combinator, insert an implicit any-element `*`
							tokens.slice( 0, i - 1 )
								.concat( { value: tokens[ i - 2 ].type === " " ? "*" : "" } )
						).replace( rtrimCSS, "$1" ),
						matcher,
						i < j && matcherFromTokens( tokens.slice( i, j ) ),
						j < len && matcherFromTokens( ( tokens = tokens.slice( j ) ) ),
						j < len && toSelector( tokens )
					);
				}
				matchers.push( matcher );
			}
		}

		return elementMatcher( matchers );
	}

	function matcherFromGroupMatchers( elementMatchers, setMatchers ) {
		var bySet = setMatchers.length > 0,
			byElement = elementMatchers.length > 0,
			superMatcher = function( seed, context, xml, results, outermost ) {
				var elem, j, matcher,
					matchedCount = 0,
					i = "0",
					unmatched = seed && [],
					setMatched = [],
					contextBackup = outermostContext,

					// We must always have either seed elements or outermost context
					elems = seed || byElement && Expr.find.TAG( "*", outermost ),

					// Use integer dirruns iff this is the outermost matcher
					dirrunsUnique = ( dirruns += contextBackup == null ? 1 : Math.random() || 0.1 ),
					len = elems.length;

				if ( outermost ) {

					// Support: IE 11+, Edge 17 - 18+
					// IE/Edge sometimes throw a "Permission denied" error when strict-comparing
					// two documents; shallow comparisons work.
					// eslint-disable-next-line eqeqeq
					outermostContext = context == document || context || outermost;
				}

				// Add elements passing elementMatchers directly to results
				// Support: iOS <=7 - 9 only
				// Tolerate NodeList properties (IE: "length"; Safari: <number>) matching
				// elements by id. (see trac-14142)
				for ( ; i !== len && ( elem = elems[ i ] ) != null; i++ ) {
					if ( byElement && elem ) {
						j = 0;

						// Support: IE 11+, Edge 17 - 18+
						// IE/Edge sometimes throw a "Permission denied" error when strict-comparing
						// two documents; shallow comparisons work.
						// eslint-disable-next-line eqeqeq
						if ( !context && elem.ownerDocument != document ) {
							setDocument( elem );
							xml = !documentIsHTML;
						}
						while ( ( matcher = elementMatchers[ j++ ] ) ) {
							if ( matcher( elem, context || document, xml ) ) {
								push.call( results, elem );
								break;
							}
						}
						if ( outermost ) {
							dirruns = dirrunsUnique;
						}
					}

					// Track unmatched elements for set filters
					if ( bySet ) {

						// They will have gone through all possible matchers
						if ( ( elem = !matcher && elem ) ) {
							matchedCount--;
						}

						// Lengthen the array for every element, matched or not
						if ( seed ) {
							unmatched.push( elem );
						}
					}
				}

				// `i` is now the count of elements visited above, and adding it to `matchedCount`
				// makes the latter nonnegative.
				matchedCount += i;

				// Apply set filters to unmatched elements
				// NOTE: This can be skipped if there are no unmatched elements (i.e., `matchedCount`
				// equals `i`), unless we didn't visit _any_ elements in the above loop because we have
				// no element matchers and no seed.
				// Incrementing an initially-string "0" `i` allows `i` to remain a string only in that
				// case, which will result in a "00" `matchedCount` that differs from `i` but is also
				// numerically zero.
				if ( bySet && i !== matchedCount ) {
					j = 0;
					while ( ( matcher = setMatchers[ j++ ] ) ) {
						matcher( unmatched, setMatched, context, xml );
					}

					if ( seed ) {

						// Reintegrate element matches to eliminate the need for sorting
						if ( matchedCount > 0 ) {
							while ( i-- ) {
								if ( !( unmatched[ i ] || setMatched[ i ] ) ) {
									setMatched[ i ] = pop.call( results );
								}
							}
						}

						// Discard index placeholder values to get only actual matches
						setMatched = condense( setMatched );
					}

					// Add matches to results
					push.apply( results, setMatched );

					// Seedless set matches succeeding multiple successful matchers stipulate sorting
					if ( outermost && !seed && setMatched.length > 0 &&
						( matchedCount + setMatchers.length ) > 1 ) {

						jQuery.uniqueSort( results );
					}
				}

				// Override manipulation of globals by nested matchers
				if ( outermost ) {
					dirruns = dirrunsUnique;
					outermostContext = contextBackup;
				}

				return unmatched;
			};

		return bySet ?
			markFunction( superMatcher ) :
			superMatcher;
	}

	function compile( selector, match /* Internal Use Only */ ) {
		var i,
			setMatchers = [],
			elementMatchers = [],
			cached = compilerCache[ selector + " " ];

		if ( !cached ) {

			// Generate a function of recursive functions that can be used to check each element
			if ( !match ) {
				match = tokenize( selector );
			}
			i = match.length;
			while ( i-- ) {
				cached = matcherFromTokens( match[ i ] );
				if ( cached[ expando ] ) {
					setMatchers.push( cached );
				} else {
					elementMatchers.push( cached );
				}
			}

			// Cache the compiled function
			cached = compilerCache( selector,
				matcherFromGroupMatchers( elementMatchers, setMatchers ) );

			// Save selector and tokenization
			cached.selector = selector;
		}
		return cached;
	}

	/**
	 * A low-level selection function that works with jQuery's compiled
	 *  selector functions
	 * @param {String|Function} selector A selector or a pre-compiled
	 *  selector function built with jQuery selector compile
	 * @param {Element} context
	 * @param {Array} [results]
	 * @param {Array} [seed] A set of elements to match against
	 */
	function select( selector, context, results, seed ) {
		var i, tokens, token, type, find,
			compiled = typeof selector === "function" && selector,
			match = !seed && tokenize( ( selector = compiled.selector || selector ) );

		results = results || [];

		// Try to minimize operations if there is only one selector in the list and no seed
		// (the latter of which guarantees us context)
		if ( match.length === 1 ) {

			// Reduce context if the leading compound selector is an ID
			tokens = match[ 0 ] = match[ 0 ].slice( 0 );
			if ( tokens.length > 2 && ( token = tokens[ 0 ] ).type === "ID" &&
					context.nodeType === 9 && documentIsHTML && Expr.relative[ tokens[ 1 ].type ] ) {

				context = ( Expr.find.ID(
					token.matches[ 0 ].replace( runescape, funescape ),
					context
				) || [] )[ 0 ];
				if ( !context ) {
					return results;

				// Precompiled matchers will still verify ancestry, so step up a level
				} else if ( compiled ) {
					context = context.parentNode;
				}

				selector = selector.slice( tokens.shift().value.length );
			}

			// Fetch a seed set for right-to-left matching
			i = matchExpr.needsContext.test( selector ) ? 0 : tokens.length;
			while ( i-- ) {
				token = tokens[ i ];

				// Abort if we hit a combinator
				if ( Expr.relative[ ( type = token.type ) ] ) {
					break;
				}
				if ( ( find = Expr.find[ type ] ) ) {

					// Search, expanding context for leading sibling combinators
					if ( ( seed = find(
						token.matches[ 0 ].replace( runescape, funescape ),
						rsibling.test( tokens[ 0 ].type ) &&
							testContext( context.parentNode ) || context
					) ) ) {

						// If seed is empty or no tokens remain, we can return early
						tokens.splice( i, 1 );
						selector = seed.length && toSelector( tokens );
						if ( !selector ) {
							push.apply( results, seed );
							return results;
						}

						break;
					}
				}
			}
		}

		// Compile and execute a filtering function if one is not provided
		// Provide `match` to avoid retokenization if we modified the selector above
		( compiled || compile( selector, match ) )(
			seed,
			context,
			!documentIsHTML,
			results,
			!context || rsibling.test( selector ) && testContext( context.parentNode ) || context
		);
		return results;
	}

	// One-time assignments

	// Support: Android <=4.0 - 4.1+
	// Sort stability
	support.sortStable = expando.split( "" ).sort( sortOrder ).join( "" ) === expando;

	// Initialize against the default document
	setDocument();

	// Support: Android <=4.0 - 4.1+
	// Detached nodes confoundingly follow *each other*
	support.sortDetached = assert( function( el ) {

		// Should return 1, but returns 4 (following)
		return el.compareDocumentPosition( document.createElement( "fieldset" ) ) & 1;
	} );

	jQuery.find = find;

	// Deprecated
	jQuery.expr[ ":" ] = jQuery.expr.pseudos;
	jQuery.unique = jQuery.uniqueSort;

	// These have always been private, but they used to be documented as part of
	// Sizzle so let's maintain them for now for backwards compatibility purposes.
	find.compile = compile;
	find.select = select;
	find.setDocument = setDocument;
	find.tokenize = tokenize;

	find.escape = jQuery.escapeSelector;
	find.getText = jQuery.text;
	find.isXML = jQuery.isXMLDoc;
	find.selectors = jQuery.expr;
	find.support = jQuery.support;
	find.uniqueSort = jQuery.uniqueSort;

		/* eslint-enable */

	} )();


	var dir = function( elem, dir, until ) {
		var matched = [],
			truncate = until !== undefined;

		while ( ( elem = elem[ dir ] ) && elem.nodeType !== 9 ) {
			if ( elem.nodeType === 1 ) {
				if ( truncate && jQuery( elem ).is( until ) ) {
					break;
				}
				matched.push( elem );
			}
		}
		return matched;
	};


	var siblings = function( n, elem ) {
		var matched = [];

		for ( ; n; n = n.nextSibling ) {
			if ( n.nodeType === 1 && n !== elem ) {
				matched.push( n );
			}
		}

		return matched;
	};


	var rneedsContext = jQuery.expr.match.needsContext;

	var rsingleTag = ( /^<([a-z][^\/\0>:\x20\t\r\n\f]*)[\x20\t\r\n\f]*\/?>(?:<\/\1>|)$/i );



	// Implement the identical functionality for filter and not
	function winnow( elements, qualifier, not ) {
		if ( isFunction( qualifier ) ) {
			return jQuery.grep( elements, function( elem, i ) {
				return !!qualifier.call( elem, i, elem ) !== not;
			} );
		}

		// Single element
		if ( qualifier.nodeType ) {
			return jQuery.grep( elements, function( elem ) {
				return ( elem === qualifier ) !== not;
			} );
		}

		// Arraylike of elements (jQuery, arguments, Array)
		if ( typeof qualifier !== "string" ) {
			return jQuery.grep( elements, function( elem ) {
				return ( indexOf.call( qualifier, elem ) > -1 ) !== not;
			} );
		}

		// Filtered directly for both simple and complex selectors
		return jQuery.filter( qualifier, elements, not );
	}

	jQuery.filter = function( expr, elems, not ) {
		var elem = elems[ 0 ];

		if ( not ) {
			expr = ":not(" + expr + ")";
		}

		if ( elems.length === 1 && elem.nodeType === 1 ) {
			return jQuery.find.matchesSelector( elem, expr ) ? [ elem ] : [];
		}

		return jQuery.find.matches( expr, jQuery.grep( elems, function( elem ) {
			return elem.nodeType === 1;
		} ) );
	};

	jQuery.fn.extend( {
		find: function( selector ) {
			var i, ret,
				len = this.length,
				self = this;

			if ( typeof selector !== "string" ) {
				return this.pushStack( jQuery( selector ).filter( function() {
					for ( i = 0; i < len; i++ ) {
						if ( jQuery.contains( self[ i ], this ) ) {
							return true;
						}
					}
				} ) );
			}

			ret = this.pushStack( [] );

			for ( i = 0; i < len; i++ ) {
				jQuery.find( selector, self[ i ], ret );
			}

			return len > 1 ? jQuery.uniqueSort( ret ) : ret;
		},
		filter: function( selector ) {
			return this.pushStack( winnow( this, selector || [], false ) );
		},
		not: function( selector ) {
			return this.pushStack( winnow( this, selector || [], true ) );
		},
		is: function( selector ) {
			return !!winnow(
				this,

				// If this is a positional/relative selector, check membership in the returned set
				// so $("p:first").is("p:last") won't return true for a doc with two "p".
				typeof selector === "string" && rneedsContext.test( selector ) ?
					jQuery( selector ) :
					selector || [],
				false
			).length;
		}
	} );


	// Initialize a jQuery object


	// A central reference to the root jQuery(document)
	var rootjQuery,

		// A simple way to check for HTML strings
		// Prioritize #id over <tag> to avoid XSS via location.hash (trac-9521)
		// Strict HTML recognition (trac-11290: must start with <)
		// Shortcut simple #id case for speed
		rquickExpr = /^(?:\s*(<[\w\W]+>)[^>]*|#([\w-]+))$/,

		init = jQuery.fn.init = function( selector, context, root ) {
			var match, elem;

			// HANDLE: $(""), $(null), $(undefined), $(false)
			if ( !selector ) {
				return this;
			}

			// Method init() accepts an alternate rootjQuery
			// so migrate can support jQuery.sub (gh-2101)
			root = root || rootjQuery;

			// Handle HTML strings
			if ( typeof selector === "string" ) {
				if ( selector[ 0 ] === "<" &&
					selector[ selector.length - 1 ] === ">" &&
					selector.length >= 3 ) {

					// Assume that strings that start and end with <> are HTML and skip the regex check
					match = [ null, selector, null ];

				} else {
					match = rquickExpr.exec( selector );
				}

				// Match html or make sure no context is specified for #id
				if ( match && ( match[ 1 ] || !context ) ) {

					// HANDLE: $(html) -> $(array)
					if ( match[ 1 ] ) {
						context = context instanceof jQuery ? context[ 0 ] : context;

						// Option to run scripts is true for back-compat
						// Intentionally let the error be thrown if parseHTML is not present
						jQuery.merge( this, jQuery.parseHTML(
							match[ 1 ],
							context && context.nodeType ? context.ownerDocument || context : document,
							true
						) );

						// HANDLE: $(html, props)
						if ( rsingleTag.test( match[ 1 ] ) && jQuery.isPlainObject( context ) ) {
							for ( match in context ) {

								// Properties of context are called as methods if possible
								if ( isFunction( this[ match ] ) ) {
									this[ match ]( context[ match ] );

								// ...and otherwise set as attributes
								} else {
									this.attr( match, context[ match ] );
								}
							}
						}

						return this;

					// HANDLE: $(#id)
					} else {
						elem = document.getElementById( match[ 2 ] );

						if ( elem ) {

							// Inject the element directly into the jQuery object
							this[ 0 ] = elem;
							this.length = 1;
						}
						return this;
					}

				// HANDLE: $(expr, $(...))
				} else if ( !context || context.jquery ) {
					return ( context || root ).find( selector );

				// HANDLE: $(expr, context)
				// (which is just equivalent to: $(context).find(expr)
				} else {
					return this.constructor( context ).find( selector );
				}

			// HANDLE: $(DOMElement)
			} else if ( selector.nodeType ) {
				this[ 0 ] = selector;
				this.length = 1;
				return this;

			// HANDLE: $(function)
			// Shortcut for document ready
			} else if ( isFunction( selector ) ) {
				return root.ready !== undefined ?
					root.ready( selector ) :

					// Execute immediately if ready is not present
					selector( jQuery );
			}

			return jQuery.makeArray( selector, this );
		};

	// Give the init function the jQuery prototype for later instantiation
	init.prototype = jQuery.fn;

	// Initialize central reference
	rootjQuery = jQuery( document );


	var rparentsprev = /^(?:parents|prev(?:Until|All))/,

		// Methods guaranteed to produce a unique set when starting from a unique set
		guaranteedUnique = {
			children: true,
			contents: true,
			next: true,
			prev: true
		};

	jQuery.fn.extend( {
		has: function( target ) {
			var targets = jQuery( target, this ),
				l = targets.length;

			return this.filter( function() {
				var i = 0;
				for ( ; i < l; i++ ) {
					if ( jQuery.contains( this, targets[ i ] ) ) {
						return true;
					}
				}
			} );
		},

		closest: function( selectors, context ) {
			var cur,
				i = 0,
				l = this.length,
				matched = [],
				targets = typeof selectors !== "string" && jQuery( selectors );

			// Positional selectors never match, since there's no _selection_ context
			if ( !rneedsContext.test( selectors ) ) {
				for ( ; i < l; i++ ) {
					for ( cur = this[ i ]; cur && cur !== context; cur = cur.parentNode ) {

						// Always skip document fragments
						if ( cur.nodeType < 11 && ( targets ?
							targets.index( cur ) > -1 :

							// Don't pass non-elements to jQuery#find
							cur.nodeType === 1 &&
								jQuery.find.matchesSelector( cur, selectors ) ) ) {

							matched.push( cur );
							break;
						}
					}
				}
			}

			return this.pushStack( matched.length > 1 ? jQuery.uniqueSort( matched ) : matched );
		},

		// Determine the position of an element within the set
		index: function( elem ) {

			// No argument, return index in parent
			if ( !elem ) {
				return ( this[ 0 ] && this[ 0 ].parentNode ) ? this.first().prevAll().length : -1;
			}

			// Index in selector
			if ( typeof elem === "string" ) {
				return indexOf.call( jQuery( elem ), this[ 0 ] );
			}

			// Locate the position of the desired element
			return indexOf.call( this,

				// If it receives a jQuery object, the first element is used
				elem.jquery ? elem[ 0 ] : elem
			);
		},

		add: function( selector, context ) {
			return this.pushStack(
				jQuery.uniqueSort(
					jQuery.merge( this.get(), jQuery( selector, context ) )
				)
			);
		},

		addBack: function( selector ) {
			return this.add( selector == null ?
				this.prevObject : this.prevObject.filter( selector )
			);
		}
	} );

	function sibling( cur, dir ) {
		while ( ( cur = cur[ dir ] ) && cur.nodeType !== 1 ) {}
		return cur;
	}

	jQuery.each( {
		parent: function( elem ) {
			var parent = elem.parentNode;
			return parent && parent.nodeType !== 11 ? parent : null;
		},
		parents: function( elem ) {
			return dir( elem, "parentNode" );
		},
		parentsUntil: function( elem, _i, until ) {
			return dir( elem, "parentNode", until );
		},
		next: function( elem ) {
			return sibling( elem, "nextSibling" );
		},
		prev: function( elem ) {
			return sibling( elem, "previousSibling" );
		},
		nextAll: function( elem ) {
			return dir( elem, "nextSibling" );
		},
		prevAll: function( elem ) {
			return dir( elem, "previousSibling" );
		},
		nextUntil: function( elem, _i, until ) {
			return dir( elem, "nextSibling", until );
		},
		prevUntil: function( elem, _i, until ) {
			return dir( elem, "previousSibling", until );
		},
		siblings: function( elem ) {
			return siblings( ( elem.parentNode || {} ).firstChild, elem );
		},
		children: function( elem ) {
			return siblings( elem.firstChild );
		},
		contents: function( elem ) {
			if ( elem.contentDocument != null &&

				// Support: IE 11+
				// <object> elements with no `data` attribute has an object
				// `contentDocument` with a `null` prototype.
				getProto( elem.contentDocument ) ) {

				return elem.contentDocument;
			}

			// Support: IE 9 - 11 only, iOS 7 only, Android Browser <=4.3 only
			// Treat the template element as a regular one in browsers that
			// don't support it.
			if ( nodeName( elem, "template" ) ) {
				elem = elem.content || elem;
			}

			return jQuery.merge( [], elem.childNodes );
		}
	}, function( name, fn ) {
		jQuery.fn[ name ] = function( until, selector ) {
			var matched = jQuery.map( this, fn, until );

			if ( name.slice( -5 ) !== "Until" ) {
				selector = until;
			}

			if ( selector && typeof selector === "string" ) {
				matched = jQuery.filter( selector, matched );
			}

			if ( this.length > 1 ) {

				// Remove duplicates
				if ( !guaranteedUnique[ name ] ) {
					jQuery.uniqueSort( matched );
				}

				// Reverse order for parents* and prev-derivatives
				if ( rparentsprev.test( name ) ) {
					matched.reverse();
				}
			}

			return this.pushStack( matched );
		};
	} );
	var rnothtmlwhite = ( /[^\x20\t\r\n\f]+/g );



	// Convert String-formatted options into Object-formatted ones
	function createOptions( options ) {
		var object = {};
		jQuery.each( options.match( rnothtmlwhite ) || [], function( _, flag ) {
			object[ flag ] = true;
		} );
		return object;
	}

	/*
	 * Create a callback list using the following parameters:
	 *
	 *	options: an optional list of space-separated options that will change how
	 *			the callback list behaves or a more traditional option object
	 *
	 * By default a callback list will act like an event callback list and can be
	 * "fired" multiple times.
	 *
	 * Possible options:
	 *
	 *	once:			will ensure the callback list can only be fired once (like a Deferred)
	 *
	 *	memory:			will keep track of previous values and will call any callback added
	 *					after the list has been fired right away with the latest "memorized"
	 *					values (like a Deferred)
	 *
	 *	unique:			will ensure a callback can only be added once (no duplicate in the list)
	 *
	 *	stopOnFalse:	interrupt callings when a callback returns false
	 *
	 */
	jQuery.Callbacks = function( options ) {

		// Convert options from String-formatted to Object-formatted if needed
		// (we check in cache first)
		options = typeof options === "string" ?
			createOptions( options ) :
			jQuery.extend( {}, options );

		var // Flag to know if list is currently firing
			firing,

			// Last fire value for non-forgettable lists
			memory,

			// Flag to know if list was already fired
			fired,

			// Flag to prevent firing
			locked,

			// Actual callback list
			list = [],

			// Queue of execution data for repeatable lists
			queue = [],

			// Index of currently firing callback (modified by add/remove as needed)
			firingIndex = -1,

			// Fire callbacks
			fire = function() {

				// Enforce single-firing
				locked = locked || options.once;

				// Execute callbacks for all pending executions,
				// respecting firingIndex overrides and runtime changes
				fired = firing = true;
				for ( ; queue.length; firingIndex = -1 ) {
					memory = queue.shift();
					while ( ++firingIndex < list.length ) {

						// Run callback and check for early termination
						if ( list[ firingIndex ].apply( memory[ 0 ], memory[ 1 ] ) === false &&
							options.stopOnFalse ) {

							// Jump to end and forget the data so .add doesn't re-fire
							firingIndex = list.length;
							memory = false;
						}
					}
				}

				// Forget the data if we're done with it
				if ( !options.memory ) {
					memory = false;
				}

				firing = false;

				// Clean up if we're done firing for good
				if ( locked ) {

					// Keep an empty list if we have data for future add calls
					if ( memory ) {
						list = [];

					// Otherwise, this object is spent
					} else {
						list = "";
					}
				}
			},

			// Actual Callbacks object
			self = {

				// Add a callback or a collection of callbacks to the list
				add: function() {
					if ( list ) {

						// If we have memory from a past run, we should fire after adding
						if ( memory && !firing ) {
							firingIndex = list.length - 1;
							queue.push( memory );
						}

						( function add( args ) {
							jQuery.each( args, function( _, arg ) {
								if ( isFunction( arg ) ) {
									if ( !options.unique || !self.has( arg ) ) {
										list.push( arg );
									}
								} else if ( arg && arg.length && toType( arg ) !== "string" ) {

									// Inspect recursively
									add( arg );
								}
							} );
						} )( arguments );

						if ( memory && !firing ) {
							fire();
						}
					}
					return this;
				},

				// Remove a callback from the list
				remove: function() {
					jQuery.each( arguments, function( _, arg ) {
						var index;
						while ( ( index = jQuery.inArray( arg, list, index ) ) > -1 ) {
							list.splice( index, 1 );

							// Handle firing indexes
							if ( index <= firingIndex ) {
								firingIndex--;
							}
						}
					} );
					return this;
				},

				// Check if a given callback is in the list.
				// If no argument is given, return whether or not list has callbacks attached.
				has: function( fn ) {
					return fn ?
						jQuery.inArray( fn, list ) > -1 :
						list.length > 0;
				},

				// Remove all callbacks from the list
				empty: function() {
					if ( list ) {
						list = [];
					}
					return this;
				},

				// Disable .fire and .add
				// Abort any current/pending executions
				// Clear all callbacks and values
				disable: function() {
					locked = queue = [];
					list = memory = "";
					return this;
				},
				disabled: function() {
					return !list;
				},

				// Disable .fire
				// Also disable .add unless we have memory (since it would have no effect)
				// Abort any pending executions
				lock: function() {
					locked = queue = [];
					if ( !memory && !firing ) {
						list = memory = "";
					}
					return this;
				},
				locked: function() {
					return !!locked;
				},

				// Call all callbacks with the given context and arguments
				fireWith: function( context, args ) {
					if ( !locked ) {
						args = args || [];
						args = [ context, args.slice ? args.slice() : args ];
						queue.push( args );
						if ( !firing ) {
							fire();
						}
					}
					return this;
				},

				// Call all the callbacks with the given arguments
				fire: function() {
					self.fireWith( this, arguments );
					return this;
				},

				// To know if the callbacks have already been called at least once
				fired: function() {
					return !!fired;
				}
			};

		return self;
	};


	function Identity( v ) {
		return v;
	}
	function Thrower( ex ) {
		throw ex;
	}

	function adoptValue( value, resolve, reject, noValue ) {
		var method;

		try {

			// Check for promise aspect first to privilege synchronous behavior
			if ( value && isFunction( ( method = value.promise ) ) ) {
				method.call( value ).done( resolve ).fail( reject );

			// Other thenables
			} else if ( value && isFunction( ( method = value.then ) ) ) {
				method.call( value, resolve, reject );

			// Other non-thenables
			} else {

				// Control `resolve` arguments by letting Array#slice cast boolean `noValue` to integer:
				// * false: [ value ].slice( 0 ) => resolve( value )
				// * true: [ value ].slice( 1 ) => resolve()
				resolve.apply( undefined, [ value ].slice( noValue ) );
			}

		// For Promises/A+, convert exceptions into rejections
		// Since jQuery.when doesn't unwrap thenables, we can skip the extra checks appearing in
		// Deferred#then to conditionally suppress rejection.
		} catch ( value ) {

			// Support: Android 4.0 only
			// Strict mode functions invoked without .call/.apply get global-object context
			reject.apply( undefined, [ value ] );
		}
	}

	jQuery.extend( {

		Deferred: function( func ) {
			var tuples = [

					// action, add listener, callbacks,
					// ... .then handlers, argument index, [final state]
					[ "notify", "progress", jQuery.Callbacks( "memory" ),
						jQuery.Callbacks( "memory" ), 2 ],
					[ "resolve", "done", jQuery.Callbacks( "once memory" ),
						jQuery.Callbacks( "once memory" ), 0, "resolved" ],
					[ "reject", "fail", jQuery.Callbacks( "once memory" ),
						jQuery.Callbacks( "once memory" ), 1, "rejected" ]
				],
				state = "pending",
				promise = {
					state: function() {
						return state;
					},
					always: function() {
						deferred.done( arguments ).fail( arguments );
						return this;
					},
					"catch": function( fn ) {
						return promise.then( null, fn );
					},

					// Keep pipe for back-compat
					pipe: function( /* fnDone, fnFail, fnProgress */ ) {
						var fns = arguments;

						return jQuery.Deferred( function( newDefer ) {
							jQuery.each( tuples, function( _i, tuple ) {

								// Map tuples (progress, done, fail) to arguments (done, fail, progress)
								var fn = isFunction( fns[ tuple[ 4 ] ] ) && fns[ tuple[ 4 ] ];

								// deferred.progress(function() { bind to newDefer or newDefer.notify })
								// deferred.done(function() { bind to newDefer or newDefer.resolve })
								// deferred.fail(function() { bind to newDefer or newDefer.reject })
								deferred[ tuple[ 1 ] ]( function() {
									var returned = fn && fn.apply( this, arguments );
									if ( returned && isFunction( returned.promise ) ) {
										returned.promise()
											.progress( newDefer.notify )
											.done( newDefer.resolve )
											.fail( newDefer.reject );
									} else {
										newDefer[ tuple[ 0 ] + "With" ](
											this,
											fn ? [ returned ] : arguments
										);
									}
								} );
							} );
							fns = null;
						} ).promise();
					},
					then: function( onFulfilled, onRejected, onProgress ) {
						var maxDepth = 0;
						function resolve( depth, deferred, handler, special ) {
							return function() {
								var that = this,
									args = arguments,
									mightThrow = function() {
										var returned, then;

										// Support: Promises/A+ section 2.3.3.3.3
										// https://promisesaplus.com/#point-59
										// Ignore double-resolution attempts
										if ( depth < maxDepth ) {
											return;
										}

										returned = handler.apply( that, args );

										// Support: Promises/A+ section 2.3.1
										// https://promisesaplus.com/#point-48
										if ( returned === deferred.promise() ) {
											throw new TypeError( "Thenable self-resolution" );
										}

										// Support: Promises/A+ sections 2.3.3.1, 3.5
										// https://promisesaplus.com/#point-54
										// https://promisesaplus.com/#point-75
										// Retrieve `then` only once
										then = returned &&

											// Support: Promises/A+ section 2.3.4
											// https://promisesaplus.com/#point-64
											// Only check objects and functions for thenability
											( typeof returned === "object" ||
												typeof returned === "function" ) &&
											returned.then;

										// Handle a returned thenable
										if ( isFunction( then ) ) {

											// Special processors (notify) just wait for resolution
											if ( special ) {
												then.call(
													returned,
													resolve( maxDepth, deferred, Identity, special ),
													resolve( maxDepth, deferred, Thrower, special )
												);

											// Normal processors (resolve) also hook into progress
											} else {

												// ...and disregard older resolution values
												maxDepth++;

												then.call(
													returned,
													resolve( maxDepth, deferred, Identity, special ),
													resolve( maxDepth, deferred, Thrower, special ),
													resolve( maxDepth, deferred, Identity,
														deferred.notifyWith )
												);
											}

										// Handle all other returned values
										} else {

											// Only substitute handlers pass on context
											// and multiple values (non-spec behavior)
											if ( handler !== Identity ) {
												that = undefined;
												args = [ returned ];
											}

											// Process the value(s)
											// Default process is resolve
											( special || deferred.resolveWith )( that, args );
										}
									},

									// Only normal processors (resolve) catch and reject exceptions
									process = special ?
										mightThrow :
										function() {
											try {
												mightThrow();
											} catch ( e ) {

												if ( jQuery.Deferred.exceptionHook ) {
													jQuery.Deferred.exceptionHook( e,
														process.error );
												}

												// Support: Promises/A+ section 2.3.3.3.4.1
												// https://promisesaplus.com/#point-61
												// Ignore post-resolution exceptions
												if ( depth + 1 >= maxDepth ) {

													// Only substitute handlers pass on context
													// and multiple values (non-spec behavior)
													if ( handler !== Thrower ) {
														that = undefined;
														args = [ e ];
													}

													deferred.rejectWith( that, args );
												}
											}
										};

								// Support: Promises/A+ section 2.3.3.3.1
								// https://promisesaplus.com/#point-57
								// Re-resolve promises immediately to dodge false rejection from
								// subsequent errors
								if ( depth ) {
									process();
								} else {

									// Call an optional hook to record the error, in case of exception
									// since it's otherwise lost when execution goes async
									if ( jQuery.Deferred.getErrorHook ) {
										process.error = jQuery.Deferred.getErrorHook();

									// The deprecated alias of the above. While the name suggests
									// returning the stack, not an error instance, jQuery just passes
									// it directly to `console.warn` so both will work; an instance
									// just better cooperates with source maps.
									} else if ( jQuery.Deferred.getStackHook ) {
										process.error = jQuery.Deferred.getStackHook();
									}
									window.setTimeout( process );
								}
							};
						}

						return jQuery.Deferred( function( newDefer ) {

							// progress_handlers.add( ... )
							tuples[ 0 ][ 3 ].add(
								resolve(
									0,
									newDefer,
									isFunction( onProgress ) ?
										onProgress :
										Identity,
									newDefer.notifyWith
								)
							);

							// fulfilled_handlers.add( ... )
							tuples[ 1 ][ 3 ].add(
								resolve(
									0,
									newDefer,
									isFunction( onFulfilled ) ?
										onFulfilled :
										Identity
								)
							);

							// rejected_handlers.add( ... )
							tuples[ 2 ][ 3 ].add(
								resolve(
									0,
									newDefer,
									isFunction( onRejected ) ?
										onRejected :
										Thrower
								)
							);
						} ).promise();
					},

					// Get a promise for this deferred
					// If obj is provided, the promise aspect is added to the object
					promise: function( obj ) {
						return obj != null ? jQuery.extend( obj, promise ) : promise;
					}
				},
				deferred = {};

			// Add list-specific methods
			jQuery.each( tuples, function( i, tuple ) {
				var list = tuple[ 2 ],
					stateString = tuple[ 5 ];

				// promise.progress = list.add
				// promise.done = list.add
				// promise.fail = list.add
				promise[ tuple[ 1 ] ] = list.add;

				// Handle state
				if ( stateString ) {
					list.add(
						function() {

							// state = "resolved" (i.e., fulfilled)
							// state = "rejected"
							state = stateString;
						},

						// rejected_callbacks.disable
						// fulfilled_callbacks.disable
						tuples[ 3 - i ][ 2 ].disable,

						// rejected_handlers.disable
						// fulfilled_handlers.disable
						tuples[ 3 - i ][ 3 ].disable,

						// progress_callbacks.lock
						tuples[ 0 ][ 2 ].lock,

						// progress_handlers.lock
						tuples[ 0 ][ 3 ].lock
					);
				}

				// progress_handlers.fire
				// fulfilled_handlers.fire
				// rejected_handlers.fire
				list.add( tuple[ 3 ].fire );

				// deferred.notify = function() { deferred.notifyWith(...) }
				// deferred.resolve = function() { deferred.resolveWith(...) }
				// deferred.reject = function() { deferred.rejectWith(...) }
				deferred[ tuple[ 0 ] ] = function() {
					deferred[ tuple[ 0 ] + "With" ]( this === deferred ? undefined : this, arguments );
					return this;
				};

				// deferred.notifyWith = list.fireWith
				// deferred.resolveWith = list.fireWith
				// deferred.rejectWith = list.fireWith
				deferred[ tuple[ 0 ] + "With" ] = list.fireWith;
			} );

			// Make the deferred a promise
			promise.promise( deferred );

			// Call given func if any
			if ( func ) {
				func.call( deferred, deferred );
			}

			// All done!
			return deferred;
		},

		// Deferred helper
		when: function( singleValue ) {
			var

				// count of uncompleted subordinates
				remaining = arguments.length,

				// count of unprocessed arguments
				i = remaining,

				// subordinate fulfillment data
				resolveContexts = Array( i ),
				resolveValues = slice.call( arguments ),

				// the primary Deferred
				primary = jQuery.Deferred(),

				// subordinate callback factory
				updateFunc = function( i ) {
					return function( value ) {
						resolveContexts[ i ] = this;
						resolveValues[ i ] = arguments.length > 1 ? slice.call( arguments ) : value;
						if ( !( --remaining ) ) {
							primary.resolveWith( resolveContexts, resolveValues );
						}
					};
				};

			// Single- and empty arguments are adopted like Promise.resolve
			if ( remaining <= 1 ) {
				adoptValue( singleValue, primary.done( updateFunc( i ) ).resolve, primary.reject,
					!remaining );

				// Use .then() to unwrap secondary thenables (cf. gh-3000)
				if ( primary.state() === "pending" ||
					isFunction( resolveValues[ i ] && resolveValues[ i ].then ) ) {

					return primary.then();
				}
			}

			// Multiple arguments are aggregated like Promise.all array elements
			while ( i-- ) {
				adoptValue( resolveValues[ i ], updateFunc( i ), primary.reject );
			}

			return primary.promise();
		}
	} );


	// These usually indicate a programmer mistake during development,
	// warn about them ASAP rather than swallowing them by default.
	var rerrorNames = /^(Eval|Internal|Range|Reference|Syntax|Type|URI)Error$/;

	// If `jQuery.Deferred.getErrorHook` is defined, `asyncError` is an error
	// captured before the async barrier to get the original error cause
	// which may otherwise be hidden.
	jQuery.Deferred.exceptionHook = function( error, asyncError ) {

		// Support: IE 8 - 9 only
		// Console exists when dev tools are open, which can happen at any time
		if ( window.console && window.console.warn && error && rerrorNames.test( error.name ) ) {
			window.console.warn( "jQuery.Deferred exception: " + error.message,
				error.stack, asyncError );
		}
	};




	jQuery.readyException = function( error ) {
		window.setTimeout( function() {
			throw error;
		} );
	};




	// The deferred used on DOM ready
	var readyList = jQuery.Deferred();

	jQuery.fn.ready = function( fn ) {

		readyList
			.then( fn )

			// Wrap jQuery.readyException in a function so that the lookup
			// happens at the time of error handling instead of callback
			// registration.
			.catch( function( error ) {
				jQuery.readyException( error );
			} );

		return this;
	};

	jQuery.extend( {

		// Is the DOM ready to be used? Set to true once it occurs.
		isReady: false,

		// A counter to track how many items to wait for before
		// the ready event fires. See trac-6781
		readyWait: 1,

		// Handle when the DOM is ready
		ready: function( wait ) {

			// Abort if there are pending holds or we're already ready
			if ( wait === true ? --jQuery.readyWait : jQuery.isReady ) {
				return;
			}

			// Remember that the DOM is ready
			jQuery.isReady = true;

			// If a normal DOM Ready event fired, decrement, and wait if need be
			if ( wait !== true && --jQuery.readyWait > 0 ) {
				return;
			}

			// If there are functions bound, to execute
			readyList.resolveWith( document, [ jQuery ] );
		}
	} );

	jQuery.ready.then = readyList.then;

	// The ready event handler and self cleanup method
	function completed() {
		document.removeEventListener( "DOMContentLoaded", completed );
		window.removeEventListener( "load", completed );
		jQuery.ready();
	}

	// Catch cases where $(document).ready() is called
	// after the browser event has already occurred.
	// Support: IE <=9 - 10 only
	// Older IE sometimes signals "interactive" too soon
	if ( document.readyState === "complete" ||
		( document.readyState !== "loading" && !document.documentElement.doScroll ) ) {

		// Handle it asynchronously to allow scripts the opportunity to delay ready
		window.setTimeout( jQuery.ready );

	} else {

		// Use the handy event callback
		document.addEventListener( "DOMContentLoaded", completed );

		// A fallback to window.onload, that will always work
		window.addEventListener( "load", completed );
	}




	// Multifunctional method to get and set values of a collection
	// The value/s can optionally be executed if it's a function
	var access = function( elems, fn, key, value, chainable, emptyGet, raw ) {
		var i = 0,
			len = elems.length,
			bulk = key == null;

		// Sets many values
		if ( toType( key ) === "object" ) {
			chainable = true;
			for ( i in key ) {
				access( elems, fn, i, key[ i ], true, emptyGet, raw );
			}

		// Sets one value
		} else if ( value !== undefined ) {
			chainable = true;

			if ( !isFunction( value ) ) {
				raw = true;
			}

			if ( bulk ) {

				// Bulk operations run against the entire set
				if ( raw ) {
					fn.call( elems, value );
					fn = null;

				// ...except when executing function values
				} else {
					bulk = fn;
					fn = function( elem, _key, value ) {
						return bulk.call( jQuery( elem ), value );
					};
				}
			}

			if ( fn ) {
				for ( ; i < len; i++ ) {
					fn(
						elems[ i ], key, raw ?
							value :
							value.call( elems[ i ], i, fn( elems[ i ], key ) )
					);
				}
			}
		}

		if ( chainable ) {
			return elems;
		}

		// Gets
		if ( bulk ) {
			return fn.call( elems );
		}

		return len ? fn( elems[ 0 ], key ) : emptyGet;
	};


	// Matches dashed string for camelizing
	var rmsPrefix = /^-ms-/,
		rdashAlpha = /-([a-z])/g;

	// Used by camelCase as callback to replace()
	function fcamelCase( _all, letter ) {
		return letter.toUpperCase();
	}

	// Convert dashed to camelCase; used by the css and data modules
	// Support: IE <=9 - 11, Edge 12 - 15
	// Microsoft forgot to hump their vendor prefix (trac-9572)
	function camelCase( string ) {
		return string.replace( rmsPrefix, "ms-" ).replace( rdashAlpha, fcamelCase );
	}
	var acceptData = function( owner ) {

		// Accepts only:
		//  - Node
		//    - Node.ELEMENT_NODE
		//    - Node.DOCUMENT_NODE
		//  - Object
		//    - Any
		return owner.nodeType === 1 || owner.nodeType === 9 || !( +owner.nodeType );
	};




	function Data() {
		this.expando = jQuery.expando + Data.uid++;
	}

	Data.uid = 1;

	Data.prototype = {

		cache: function( owner ) {

			// Check if the owner object already has a cache
			var value = owner[ this.expando ];

			// If not, create one
			if ( !value ) {
				value = {};

				// We can accept data for non-element nodes in modern browsers,
				// but we should not, see trac-8335.
				// Always return an empty object.
				if ( acceptData( owner ) ) {

					// If it is a node unlikely to be stringify-ed or looped over
					// use plain assignment
					if ( owner.nodeType ) {
						owner[ this.expando ] = value;

					// Otherwise secure it in a non-enumerable property
					// configurable must be true to allow the property to be
					// deleted when data is removed
					} else {
						Object.defineProperty( owner, this.expando, {
							value: value,
							configurable: true
						} );
					}
				}
			}

			return value;
		},
		set: function( owner, data, value ) {
			var prop,
				cache = this.cache( owner );

			// Handle: [ owner, key, value ] args
			// Always use camelCase key (gh-2257)
			if ( typeof data === "string" ) {
				cache[ camelCase( data ) ] = value;

			// Handle: [ owner, { properties } ] args
			} else {

				// Copy the properties one-by-one to the cache object
				for ( prop in data ) {
					cache[ camelCase( prop ) ] = data[ prop ];
				}
			}
			return cache;
		},
		get: function( owner, key ) {
			return key === undefined ?
				this.cache( owner ) :

				// Always use camelCase key (gh-2257)
				owner[ this.expando ] && owner[ this.expando ][ camelCase( key ) ];
		},
		access: function( owner, key, value ) {

			// In cases where either:
			//
			//   1. No key was specified
			//   2. A string key was specified, but no value provided
			//
			// Take the "read" path and allow the get method to determine
			// which value to return, respectively either:
			//
			//   1. The entire cache object
			//   2. The data stored at the key
			//
			if ( key === undefined ||
					( ( key && typeof key === "string" ) && value === undefined ) ) {

				return this.get( owner, key );
			}

			// When the key is not a string, or both a key and value
			// are specified, set or extend (existing objects) with either:
			//
			//   1. An object of properties
			//   2. A key and value
			//
			this.set( owner, key, value );

			// Since the "set" path can have two possible entry points
			// return the expected data based on which path was taken[*]
			return value !== undefined ? value : key;
		},
		remove: function( owner, key ) {
			var i,
				cache = owner[ this.expando ];

			if ( cache === undefined ) {
				return;
			}

			if ( key !== undefined ) {

				// Support array or space separated string of keys
				if ( Array.isArray( key ) ) {

					// If key is an array of keys...
					// We always set camelCase keys, so remove that.
					key = key.map( camelCase );
				} else {
					key = camelCase( key );

					// If a key with the spaces exists, use it.
					// Otherwise, create an array by matching non-whitespace
					key = key in cache ?
						[ key ] :
						( key.match( rnothtmlwhite ) || [] );
				}

				i = key.length;

				while ( i-- ) {
					delete cache[ key[ i ] ];
				}
			}

			// Remove the expando if there's no more data
			if ( key === undefined || jQuery.isEmptyObject( cache ) ) {

				// Support: Chrome <=35 - 45
				// Webkit & Blink performance suffers when deleting properties
				// from DOM nodes, so set to undefined instead
				// https://bugs.chromium.org/p/chromium/issues/detail?id=378607 (bug restricted)
				if ( owner.nodeType ) {
					owner[ this.expando ] = undefined;
				} else {
					delete owner[ this.expando ];
				}
			}
		},
		hasData: function( owner ) {
			var cache = owner[ this.expando ];
			return cache !== undefined && !jQuery.isEmptyObject( cache );
		}
	};
	var dataPriv = new Data();

	var dataUser = new Data();



	//	Implementation Summary
	//
	//	1. Enforce API surface and semantic compatibility with 1.9.x branch
	//	2. Improve the module's maintainability by reducing the storage
	//		paths to a single mechanism.
	//	3. Use the same single mechanism to support "private" and "user" data.
	//	4. _Never_ expose "private" data to user code (TODO: Drop _data, _removeData)
	//	5. Avoid exposing implementation details on user objects (eg. expando properties)
	//	6. Provide a clear path for implementation upgrade to WeakMap in 2014

	var rbrace = /^(?:\{[\w\W]*\}|\[[\w\W]*\])$/,
		rmultiDash = /[A-Z]/g;

	function getData( data ) {
		if ( data === "true" ) {
			return true;
		}

		if ( data === "false" ) {
			return false;
		}

		if ( data === "null" ) {
			return null;
		}

		// Only convert to a number if it doesn't change the string
		if ( data === +data + "" ) {
			return +data;
		}

		if ( rbrace.test( data ) ) {
			return JSON.parse( data );
		}

		return data;
	}

	function dataAttr( elem, key, data ) {
		var name;

		// If nothing was found internally, try to fetch any
		// data from the HTML5 data-* attribute
		if ( data === undefined && elem.nodeType === 1 ) {
			name = "data-" + key.replace( rmultiDash, "-$&" ).toLowerCase();
			data = elem.getAttribute( name );

			if ( typeof data === "string" ) {
				try {
					data = getData( data );
				} catch ( e ) {}

				// Make sure we set the data so it isn't changed later
				dataUser.set( elem, key, data );
			} else {
				data = undefined;
			}
		}
		return data;
	}

	jQuery.extend( {
		hasData: function( elem ) {
			return dataUser.hasData( elem ) || dataPriv.hasData( elem );
		},

		data: function( elem, name, data ) {
			return dataUser.access( elem, name, data );
		},

		removeData: function( elem, name ) {
			dataUser.remove( elem, name );
		},

		// TODO: Now that all calls to _data and _removeData have been replaced
		// with direct calls to dataPriv methods, these can be deprecated.
		_data: function( elem, name, data ) {
			return dataPriv.access( elem, name, data );
		},

		_removeData: function( elem, name ) {
			dataPriv.remove( elem, name );
		}
	} );

	jQuery.fn.extend( {
		data: function( key, value ) {
			var i, name, data,
				elem = this[ 0 ],
				attrs = elem && elem.attributes;

			// Gets all values
			if ( key === undefined ) {
				if ( this.length ) {
					data = dataUser.get( elem );

					if ( elem.nodeType === 1 && !dataPriv.get( elem, "hasDataAttrs" ) ) {
						i = attrs.length;
						while ( i-- ) {

							// Support: IE 11 only
							// The attrs elements can be null (trac-14894)
							if ( attrs[ i ] ) {
								name = attrs[ i ].name;
								if ( name.indexOf( "data-" ) === 0 ) {
									name = camelCase( name.slice( 5 ) );
									dataAttr( elem, name, data[ name ] );
								}
							}
						}
						dataPriv.set( elem, "hasDataAttrs", true );
					}
				}

				return data;
			}

			// Sets multiple values
			if ( typeof key === "object" ) {
				return this.each( function() {
					dataUser.set( this, key );
				} );
			}

			return access( this, function( value ) {
				var data;

				// The calling jQuery object (element matches) is not empty
				// (and therefore has an element appears at this[ 0 ]) and the
				// `value` parameter was not undefined. An empty jQuery object
				// will result in `undefined` for elem = this[ 0 ] which will
				// throw an exception if an attempt to read a data cache is made.
				if ( elem && value === undefined ) {

					// Attempt to get data from the cache
					// The key will always be camelCased in Data
					data = dataUser.get( elem, key );
					if ( data !== undefined ) {
						return data;
					}

					// Attempt to "discover" the data in
					// HTML5 custom data-* attrs
					data = dataAttr( elem, key );
					if ( data !== undefined ) {
						return data;
					}

					// We tried really hard, but the data doesn't exist.
					return;
				}

				// Set the data...
				this.each( function() {

					// We always store the camelCased key
					dataUser.set( this, key, value );
				} );
			}, null, value, arguments.length > 1, null, true );
		},

		removeData: function( key ) {
			return this.each( function() {
				dataUser.remove( this, key );
			} );
		}
	} );


	jQuery.extend( {
		queue: function( elem, type, data ) {
			var queue;

			if ( elem ) {
				type = ( type || "fx" ) + "queue";
				queue = dataPriv.get( elem, type );

				// Speed up dequeue by getting out quickly if this is just a lookup
				if ( data ) {
					if ( !queue || Array.isArray( data ) ) {
						queue = dataPriv.access( elem, type, jQuery.makeArray( data ) );
					} else {
						queue.push( data );
					}
				}
				return queue || [];
			}
		},

		dequeue: function( elem, type ) {
			type = type || "fx";

			var queue = jQuery.queue( elem, type ),
				startLength = queue.length,
				fn = queue.shift(),
				hooks = jQuery._queueHooks( elem, type ),
				next = function() {
					jQuery.dequeue( elem, type );
				};

			// If the fx queue is dequeued, always remove the progress sentinel
			if ( fn === "inprogress" ) {
				fn = queue.shift();
				startLength--;
			}

			if ( fn ) {

				// Add a progress sentinel to prevent the fx queue from being
				// automatically dequeued
				if ( type === "fx" ) {
					queue.unshift( "inprogress" );
				}

				// Clear up the last queue stop function
				delete hooks.stop;
				fn.call( elem, next, hooks );
			}

			if ( !startLength && hooks ) {
				hooks.empty.fire();
			}
		},

		// Not public - generate a queueHooks object, or return the current one
		_queueHooks: function( elem, type ) {
			var key = type + "queueHooks";
			return dataPriv.get( elem, key ) || dataPriv.access( elem, key, {
				empty: jQuery.Callbacks( "once memory" ).add( function() {
					dataPriv.remove( elem, [ type + "queue", key ] );
				} )
			} );
		}
	} );

	jQuery.fn.extend( {
		queue: function( type, data ) {
			var setter = 2;

			if ( typeof type !== "string" ) {
				data = type;
				type = "fx";
				setter--;
			}

			if ( arguments.length < setter ) {
				return jQuery.queue( this[ 0 ], type );
			}

			return data === undefined ?
				this :
				this.each( function() {
					var queue = jQuery.queue( this, type, data );

					// Ensure a hooks for this queue
					jQuery._queueHooks( this, type );

					if ( type === "fx" && queue[ 0 ] !== "inprogress" ) {
						jQuery.dequeue( this, type );
					}
				} );
		},
		dequeue: function( type ) {
			return this.each( function() {
				jQuery.dequeue( this, type );
			} );
		},
		clearQueue: function( type ) {
			return this.queue( type || "fx", [] );
		},

		// Get a promise resolved when queues of a certain type
		// are emptied (fx is the type by default)
		promise: function( type, obj ) {
			var tmp,
				count = 1,
				defer = jQuery.Deferred(),
				elements = this,
				i = this.length,
				resolve = function() {
					if ( !( --count ) ) {
						defer.resolveWith( elements, [ elements ] );
					}
				};

			if ( typeof type !== "string" ) {
				obj = type;
				type = undefined;
			}
			type = type || "fx";

			while ( i-- ) {
				tmp = dataPriv.get( elements[ i ], type + "queueHooks" );
				if ( tmp && tmp.empty ) {
					count++;
					tmp.empty.add( resolve );
				}
			}
			resolve();
			return defer.promise( obj );
		}
	} );
	var pnum = ( /[+-]?(?:\d*\.|)\d+(?:[eE][+-]?\d+|)/ ).source;

	var rcssNum = new RegExp( "^(?:([+-])=|)(" + pnum + ")([a-z%]*)$", "i" );


	var cssExpand = [ "Top", "Right", "Bottom", "Left" ];

	var documentElement = document.documentElement;



		var isAttached = function( elem ) {
				return jQuery.contains( elem.ownerDocument, elem );
			},
			composed = { composed: true };

		// Support: IE 9 - 11+, Edge 12 - 18+, iOS 10.0 - 10.2 only
		// Check attachment across shadow DOM boundaries when possible (gh-3504)
		// Support: iOS 10.0-10.2 only
		// Early iOS 10 versions support `attachShadow` but not `getRootNode`,
		// leading to errors. We need to check for `getRootNode`.
		if ( documentElement.getRootNode ) {
			isAttached = function( elem ) {
				return jQuery.contains( elem.ownerDocument, elem ) ||
					elem.getRootNode( composed ) === elem.ownerDocument;
			};
		}
	var isHiddenWithinTree = function( elem, el ) {

			// isHiddenWithinTree might be called from jQuery#filter function;
			// in that case, element will be second argument
			elem = el || elem;

			// Inline style trumps all
			return elem.style.display === "none" ||
				elem.style.display === "" &&

				// Otherwise, check computed style
				// Support: Firefox <=43 - 45
				// Disconnected elements can have computed display: none, so first confirm that elem is
				// in the document.
				isAttached( elem ) &&

				jQuery.css( elem, "display" ) === "none";
		};



	function adjustCSS( elem, prop, valueParts, tween ) {
		var adjusted, scale,
			maxIterations = 20,
			currentValue = tween ?
				function() {
					return tween.cur();
				} :
				function() {
					return jQuery.css( elem, prop, "" );
				},
			initial = currentValue(),
			unit = valueParts && valueParts[ 3 ] || ( jQuery.cssNumber[ prop ] ? "" : "px" ),

			// Starting value computation is required for potential unit mismatches
			initialInUnit = elem.nodeType &&
				( jQuery.cssNumber[ prop ] || unit !== "px" && +initial ) &&
				rcssNum.exec( jQuery.css( elem, prop ) );

		if ( initialInUnit && initialInUnit[ 3 ] !== unit ) {

			// Support: Firefox <=54
			// Halve the iteration target value to prevent interference from CSS upper bounds (gh-2144)
			initial = initial / 2;

			// Trust units reported by jQuery.css
			unit = unit || initialInUnit[ 3 ];

			// Iteratively approximate from a nonzero starting point
			initialInUnit = +initial || 1;

			while ( maxIterations-- ) {

				// Evaluate and update our best guess (doubling guesses that zero out).
				// Finish if the scale equals or crosses 1 (making the old*new product non-positive).
				jQuery.style( elem, prop, initialInUnit + unit );
				if ( ( 1 - scale ) * ( 1 - ( scale = currentValue() / initial || 0.5 ) ) <= 0 ) {
					maxIterations = 0;
				}
				initialInUnit = initialInUnit / scale;

			}

			initialInUnit = initialInUnit * 2;
			jQuery.style( elem, prop, initialInUnit + unit );

			// Make sure we update the tween properties later on
			valueParts = valueParts || [];
		}

		if ( valueParts ) {
			initialInUnit = +initialInUnit || +initial || 0;

			// Apply relative offset (+=/-=) if specified
			adjusted = valueParts[ 1 ] ?
				initialInUnit + ( valueParts[ 1 ] + 1 ) * valueParts[ 2 ] :
				+valueParts[ 2 ];
			if ( tween ) {
				tween.unit = unit;
				tween.start = initialInUnit;
				tween.end = adjusted;
			}
		}
		return adjusted;
	}


	var defaultDisplayMap = {};

	function getDefaultDisplay( elem ) {
		var temp,
			doc = elem.ownerDocument,
			nodeName = elem.nodeName,
			display = defaultDisplayMap[ nodeName ];

		if ( display ) {
			return display;
		}

		temp = doc.body.appendChild( doc.createElement( nodeName ) );
		display = jQuery.css( temp, "display" );

		temp.parentNode.removeChild( temp );

		if ( display === "none" ) {
			display = "block";
		}
		defaultDisplayMap[ nodeName ] = display;

		return display;
	}

	function showHide( elements, show ) {
		var display, elem,
			values = [],
			index = 0,
			length = elements.length;

		// Determine new display value for elements that need to change
		for ( ; index < length; index++ ) {
			elem = elements[ index ];
			if ( !elem.style ) {
				continue;
			}

			display = elem.style.display;
			if ( show ) {

				// Since we force visibility upon cascade-hidden elements, an immediate (and slow)
				// check is required in this first loop unless we have a nonempty display value (either
				// inline or about-to-be-restored)
				if ( display === "none" ) {
					values[ index ] = dataPriv.get( elem, "display" ) || null;
					if ( !values[ index ] ) {
						elem.style.display = "";
					}
				}
				if ( elem.style.display === "" && isHiddenWithinTree( elem ) ) {
					values[ index ] = getDefaultDisplay( elem );
				}
			} else {
				if ( display !== "none" ) {
					values[ index ] = "none";

					// Remember what we're overwriting
					dataPriv.set( elem, "display", display );
				}
			}
		}

		// Set the display of the elements in a second loop to avoid constant reflow
		for ( index = 0; index < length; index++ ) {
			if ( values[ index ] != null ) {
				elements[ index ].style.display = values[ index ];
			}
		}

		return elements;
	}

	jQuery.fn.extend( {
		show: function() {
			return showHide( this, true );
		},
		hide: function() {
			return showHide( this );
		},
		toggle: function( state ) {
			if ( typeof state === "boolean" ) {
				return state ? this.show() : this.hide();
			}

			return this.each( function() {
				if ( isHiddenWithinTree( this ) ) {
					jQuery( this ).show();
				} else {
					jQuery( this ).hide();
				}
			} );
		}
	} );
	var rcheckableType = ( /^(?:checkbox|radio)$/i );

	var rtagName = ( /<([a-z][^\/\0>\x20\t\r\n\f]*)/i );

	var rscriptType = ( /^$|^module$|\/(?:java|ecma)script/i );



	( function() {
		var fragment = document.createDocumentFragment(),
			div = fragment.appendChild( document.createElement( "div" ) ),
			input = document.createElement( "input" );

		// Support: Android 4.0 - 4.3 only
		// Check state lost if the name is set (trac-11217)
		// Support: Windows Web Apps (WWA)
		// `name` and `type` must use .setAttribute for WWA (trac-14901)
		input.setAttribute( "type", "radio" );
		input.setAttribute( "checked", "checked" );
		input.setAttribute( "name", "t" );

		div.appendChild( input );

		// Support: Android <=4.1 only
		// Older WebKit doesn't clone checked state correctly in fragments
		support.checkClone = div.cloneNode( true ).cloneNode( true ).lastChild.checked;

		// Support: IE <=11 only
		// Make sure textarea (and checkbox) defaultValue is properly cloned
		div.innerHTML = "<textarea>x</textarea>";
		support.noCloneChecked = !!div.cloneNode( true ).lastChild.defaultValue;

		// Support: IE <=9 only
		// IE <=9 replaces <option> tags with their contents when inserted outside of
		// the select element.
		div.innerHTML = "<option></option>";
		support.option = !!div.lastChild;
	} )();


	// We have to close these tags to support XHTML (trac-13200)
	var wrapMap = {

		// XHTML parsers do not magically insert elements in the
		// same way that tag soup parsers do. So we cannot shorten
		// this by omitting <tbody> or other required elements.
		thead: [ 1, "<table>", "</table>" ],
		col: [ 2, "<table><colgroup>", "</colgroup></table>" ],
		tr: [ 2, "<table><tbody>", "</tbody></table>" ],
		td: [ 3, "<table><tbody><tr>", "</tr></tbody></table>" ],

		_default: [ 0, "", "" ]
	};

	wrapMap.tbody = wrapMap.tfoot = wrapMap.colgroup = wrapMap.caption = wrapMap.thead;
	wrapMap.th = wrapMap.td;

	// Support: IE <=9 only
	if ( !support.option ) {
		wrapMap.optgroup = wrapMap.option = [ 1, "<select multiple='multiple'>", "</select>" ];
	}


	function getAll( context, tag ) {

		// Support: IE <=9 - 11 only
		// Use typeof to avoid zero-argument method invocation on host objects (trac-15151)
		var ret;

		if ( typeof context.getElementsByTagName !== "undefined" ) {
			ret = context.getElementsByTagName( tag || "*" );

		} else if ( typeof context.querySelectorAll !== "undefined" ) {
			ret = context.querySelectorAll( tag || "*" );

		} else {
			ret = [];
		}

		if ( tag === undefined || tag && nodeName( context, tag ) ) {
			return jQuery.merge( [ context ], ret );
		}

		return ret;
	}


	// Mark scripts as having already been evaluated
	function setGlobalEval( elems, refElements ) {
		var i = 0,
			l = elems.length;

		for ( ; i < l; i++ ) {
			dataPriv.set(
				elems[ i ],
				"globalEval",
				!refElements || dataPriv.get( refElements[ i ], "globalEval" )
			);
		}
	}


	var rhtml = /<|&#?\w+;/;

	function buildFragment( elems, context, scripts, selection, ignored ) {
		var elem, tmp, tag, wrap, attached, j,
			fragment = context.createDocumentFragment(),
			nodes = [],
			i = 0,
			l = elems.length;

		for ( ; i < l; i++ ) {
			elem = elems[ i ];

			if ( elem || elem === 0 ) {

				// Add nodes directly
				if ( toType( elem ) === "object" ) {

					// Support: Android <=4.0 only, PhantomJS 1 only
					// push.apply(_, arraylike) throws on ancient WebKit
					jQuery.merge( nodes, elem.nodeType ? [ elem ] : elem );

				// Convert non-html into a text node
				} else if ( !rhtml.test( elem ) ) {
					nodes.push( context.createTextNode( elem ) );

				// Convert html into DOM nodes
				} else {
					tmp = tmp || fragment.appendChild( context.createElement( "div" ) );

					// Deserialize a standard representation
					tag = ( rtagName.exec( elem ) || [ "", "" ] )[ 1 ].toLowerCase();
					wrap = wrapMap[ tag ] || wrapMap._default;
					tmp.innerHTML = wrap[ 1 ] + jQuery.htmlPrefilter( elem ) + wrap[ 2 ];

					// Descend through wrappers to the right content
					j = wrap[ 0 ];
					while ( j-- ) {
						tmp = tmp.lastChild;
					}

					// Support: Android <=4.0 only, PhantomJS 1 only
					// push.apply(_, arraylike) throws on ancient WebKit
					jQuery.merge( nodes, tmp.childNodes );

					// Remember the top-level container
					tmp = fragment.firstChild;

					// Ensure the created nodes are orphaned (trac-12392)
					tmp.textContent = "";
				}
			}
		}

		// Remove wrapper from fragment
		fragment.textContent = "";

		i = 0;
		while ( ( elem = nodes[ i++ ] ) ) {

			// Skip elements already in the context collection (trac-4087)
			if ( selection && jQuery.inArray( elem, selection ) > -1 ) {
				if ( ignored ) {
					ignored.push( elem );
				}
				continue;
			}

			attached = isAttached( elem );

			// Append to fragment
			tmp = getAll( fragment.appendChild( elem ), "script" );

			// Preserve script evaluation history
			if ( attached ) {
				setGlobalEval( tmp );
			}

			// Capture executables
			if ( scripts ) {
				j = 0;
				while ( ( elem = tmp[ j++ ] ) ) {
					if ( rscriptType.test( elem.type || "" ) ) {
						scripts.push( elem );
					}
				}
			}
		}

		return fragment;
	}


	var rtypenamespace = /^([^.]*)(?:\.(.+)|)/;

	function returnTrue() {
		return true;
	}

	function returnFalse() {
		return false;
	}

	function on( elem, types, selector, data, fn, one ) {
		var origFn, type;

		// Types can be a map of types/handlers
		if ( typeof types === "object" ) {

			// ( types-Object, selector, data )
			if ( typeof selector !== "string" ) {

				// ( types-Object, data )
				data = data || selector;
				selector = undefined;
			}
			for ( type in types ) {
				on( elem, type, selector, data, types[ type ], one );
			}
			return elem;
		}

		if ( data == null && fn == null ) {

			// ( types, fn )
			fn = selector;
			data = selector = undefined;
		} else if ( fn == null ) {
			if ( typeof selector === "string" ) {

				// ( types, selector, fn )
				fn = data;
				data = undefined;
			} else {

				// ( types, data, fn )
				fn = data;
				data = selector;
				selector = undefined;
			}
		}
		if ( fn === false ) {
			fn = returnFalse;
		} else if ( !fn ) {
			return elem;
		}

		if ( one === 1 ) {
			origFn = fn;
			fn = function( event ) {

				// Can use an empty set, since event contains the info
				jQuery().off( event );
				return origFn.apply( this, arguments );
			};

			// Use same guid so caller can remove using origFn
			fn.guid = origFn.guid || ( origFn.guid = jQuery.guid++ );
		}
		return elem.each( function() {
			jQuery.event.add( this, types, fn, data, selector );
		} );
	}

	/*
	 * Helper functions for managing events -- not part of the public interface.
	 * Props to Dean Edwards' addEvent library for many of the ideas.
	 */
	jQuery.event = {

		global: {},

		add: function( elem, types, handler, data, selector ) {

			var handleObjIn, eventHandle, tmp,
				events, t, handleObj,
				special, handlers, type, namespaces, origType,
				elemData = dataPriv.get( elem );

			// Only attach events to objects that accept data
			if ( !acceptData( elem ) ) {
				return;
			}

			// Caller can pass in an object of custom data in lieu of the handler
			if ( handler.handler ) {
				handleObjIn = handler;
				handler = handleObjIn.handler;
				selector = handleObjIn.selector;
			}

			// Ensure that invalid selectors throw exceptions at attach time
			// Evaluate against documentElement in case elem is a non-element node (e.g., document)
			if ( selector ) {
				jQuery.find.matchesSelector( documentElement, selector );
			}

			// Make sure that the handler has a unique ID, used to find/remove it later
			if ( !handler.guid ) {
				handler.guid = jQuery.guid++;
			}

			// Init the element's event structure and main handler, if this is the first
			if ( !( events = elemData.events ) ) {
				events = elemData.events = Object.create( null );
			}
			if ( !( eventHandle = elemData.handle ) ) {
				eventHandle = elemData.handle = function( e ) {

					// Discard the second event of a jQuery.event.trigger() and
					// when an event is called after a page has unloaded
					return typeof jQuery !== "undefined" && jQuery.event.triggered !== e.type ?
						jQuery.event.dispatch.apply( elem, arguments ) : undefined;
				};
			}

			// Handle multiple events separated by a space
			types = ( types || "" ).match( rnothtmlwhite ) || [ "" ];
			t = types.length;
			while ( t-- ) {
				tmp = rtypenamespace.exec( types[ t ] ) || [];
				type = origType = tmp[ 1 ];
				namespaces = ( tmp[ 2 ] || "" ).split( "." ).sort();

				// There *must* be a type, no attaching namespace-only handlers
				if ( !type ) {
					continue;
				}

				// If event changes its type, use the special event handlers for the changed type
				special = jQuery.event.special[ type ] || {};

				// If selector defined, determine special event api type, otherwise given type
				type = ( selector ? special.delegateType : special.bindType ) || type;

				// Update special based on newly reset type
				special = jQuery.event.special[ type ] || {};

				// handleObj is passed to all event handlers
				handleObj = jQuery.extend( {
					type: type,
					origType: origType,
					data: data,
					handler: handler,
					guid: handler.guid,
					selector: selector,
					needsContext: selector && jQuery.expr.match.needsContext.test( selector ),
					namespace: namespaces.join( "." )
				}, handleObjIn );

				// Init the event handler queue if we're the first
				if ( !( handlers = events[ type ] ) ) {
					handlers = events[ type ] = [];
					handlers.delegateCount = 0;

					// Only use addEventListener if the special events handler returns false
					if ( !special.setup ||
						special.setup.call( elem, data, namespaces, eventHandle ) === false ) {

						if ( elem.addEventListener ) {
							elem.addEventListener( type, eventHandle );
						}
					}
				}

				if ( special.add ) {
					special.add.call( elem, handleObj );

					if ( !handleObj.handler.guid ) {
						handleObj.handler.guid = handler.guid;
					}
				}

				// Add to the element's handler list, delegates in front
				if ( selector ) {
					handlers.splice( handlers.delegateCount++, 0, handleObj );
				} else {
					handlers.push( handleObj );
				}

				// Keep track of which events have ever been used, for event optimization
				jQuery.event.global[ type ] = true;
			}

		},

		// Detach an event or set of events from an element
		remove: function( elem, types, handler, selector, mappedTypes ) {

			var j, origCount, tmp,
				events, t, handleObj,
				special, handlers, type, namespaces, origType,
				elemData = dataPriv.hasData( elem ) && dataPriv.get( elem );

			if ( !elemData || !( events = elemData.events ) ) {
				return;
			}

			// Once for each type.namespace in types; type may be omitted
			types = ( types || "" ).match( rnothtmlwhite ) || [ "" ];
			t = types.length;
			while ( t-- ) {
				tmp = rtypenamespace.exec( types[ t ] ) || [];
				type = origType = tmp[ 1 ];
				namespaces = ( tmp[ 2 ] || "" ).split( "." ).sort();

				// Unbind all events (on this namespace, if provided) for the element
				if ( !type ) {
					for ( type in events ) {
						jQuery.event.remove( elem, type + types[ t ], handler, selector, true );
					}
					continue;
				}

				special = jQuery.event.special[ type ] || {};
				type = ( selector ? special.delegateType : special.bindType ) || type;
				handlers = events[ type ] || [];
				tmp = tmp[ 2 ] &&
					new RegExp( "(^|\\.)" + namespaces.join( "\\.(?:.*\\.|)" ) + "(\\.|$)" );

				// Remove matching events
				origCount = j = handlers.length;
				while ( j-- ) {
					handleObj = handlers[ j ];

					if ( ( mappedTypes || origType === handleObj.origType ) &&
						( !handler || handler.guid === handleObj.guid ) &&
						( !tmp || tmp.test( handleObj.namespace ) ) &&
						( !selector || selector === handleObj.selector ||
							selector === "**" && handleObj.selector ) ) {
						handlers.splice( j, 1 );

						if ( handleObj.selector ) {
							handlers.delegateCount--;
						}
						if ( special.remove ) {
							special.remove.call( elem, handleObj );
						}
					}
				}

				// Remove generic event handler if we removed something and no more handlers exist
				// (avoids potential for endless recursion during removal of special event handlers)
				if ( origCount && !handlers.length ) {
					if ( !special.teardown ||
						special.teardown.call( elem, namespaces, elemData.handle ) === false ) {

						jQuery.removeEvent( elem, type, elemData.handle );
					}

					delete events[ type ];
				}
			}

			// Remove data and the expando if it's no longer used
			if ( jQuery.isEmptyObject( events ) ) {
				dataPriv.remove( elem, "handle events" );
			}
		},

		dispatch: function( nativeEvent ) {

			var i, j, ret, matched, handleObj, handlerQueue,
				args = new Array( arguments.length ),

				// Make a writable jQuery.Event from the native event object
				event = jQuery.event.fix( nativeEvent ),

				handlers = (
					dataPriv.get( this, "events" ) || Object.create( null )
				)[ event.type ] || [],
				special = jQuery.event.special[ event.type ] || {};

			// Use the fix-ed jQuery.Event rather than the (read-only) native event
			args[ 0 ] = event;

			for ( i = 1; i < arguments.length; i++ ) {
				args[ i ] = arguments[ i ];
			}

			event.delegateTarget = this;

			// Call the preDispatch hook for the mapped type, and let it bail if desired
			if ( special.preDispatch && special.preDispatch.call( this, event ) === false ) {
				return;
			}

			// Determine handlers
			handlerQueue = jQuery.event.handlers.call( this, event, handlers );

			// Run delegates first; they may want to stop propagation beneath us
			i = 0;
			while ( ( matched = handlerQueue[ i++ ] ) && !event.isPropagationStopped() ) {
				event.currentTarget = matched.elem;

				j = 0;
				while ( ( handleObj = matched.handlers[ j++ ] ) &&
					!event.isImmediatePropagationStopped() ) {

					// If the event is namespaced, then each handler is only invoked if it is
					// specially universal or its namespaces are a superset of the event's.
					if ( !event.rnamespace || handleObj.namespace === false ||
						event.rnamespace.test( handleObj.namespace ) ) {

						event.handleObj = handleObj;
						event.data = handleObj.data;

						ret = ( ( jQuery.event.special[ handleObj.origType ] || {} ).handle ||
							handleObj.handler ).apply( matched.elem, args );

						if ( ret !== undefined ) {
							if ( ( event.result = ret ) === false ) {
								event.preventDefault();
								event.stopPropagation();
							}
						}
					}
				}
			}

			// Call the postDispatch hook for the mapped type
			if ( special.postDispatch ) {
				special.postDispatch.call( this, event );
			}

			return event.result;
		},

		handlers: function( event, handlers ) {
			var i, handleObj, sel, matchedHandlers, matchedSelectors,
				handlerQueue = [],
				delegateCount = handlers.delegateCount,
				cur = event.target;

			// Find delegate handlers
			if ( delegateCount &&

				// Support: IE <=9
				// Black-hole SVG <use> instance trees (trac-13180)
				cur.nodeType &&

				// Support: Firefox <=42
				// Suppress spec-violating clicks indicating a non-primary pointer button (trac-3861)
				// https://www.w3.org/TR/DOM-Level-3-Events/#event-type-click
				// Support: IE 11 only
				// ...but not arrow key "clicks" of radio inputs, which can have `button` -1 (gh-2343)
				!( event.type === "click" && event.button >= 1 ) ) {

				for ( ; cur !== this; cur = cur.parentNode || this ) {

					// Don't check non-elements (trac-13208)
					// Don't process clicks on disabled elements (trac-6911, trac-8165, trac-11382, trac-11764)
					if ( cur.nodeType === 1 && !( event.type === "click" && cur.disabled === true ) ) {
						matchedHandlers = [];
						matchedSelectors = {};
						for ( i = 0; i < delegateCount; i++ ) {
							handleObj = handlers[ i ];

							// Don't conflict with Object.prototype properties (trac-13203)
							sel = handleObj.selector + " ";

							if ( matchedSelectors[ sel ] === undefined ) {
								matchedSelectors[ sel ] = handleObj.needsContext ?
									jQuery( sel, this ).index( cur ) > -1 :
									jQuery.find( sel, this, null, [ cur ] ).length;
							}
							if ( matchedSelectors[ sel ] ) {
								matchedHandlers.push( handleObj );
							}
						}
						if ( matchedHandlers.length ) {
							handlerQueue.push( { elem: cur, handlers: matchedHandlers } );
						}
					}
				}
			}

			// Add the remaining (directly-bound) handlers
			cur = this;
			if ( delegateCount < handlers.length ) {
				handlerQueue.push( { elem: cur, handlers: handlers.slice( delegateCount ) } );
			}

			return handlerQueue;
		},

		addProp: function( name, hook ) {
			Object.defineProperty( jQuery.Event.prototype, name, {
				enumerable: true,
				configurable: true,

				get: isFunction( hook ) ?
					function() {
						if ( this.originalEvent ) {
							return hook( this.originalEvent );
						}
					} :
					function() {
						if ( this.originalEvent ) {
							return this.originalEvent[ name ];
						}
					},

				set: function( value ) {
					Object.defineProperty( this, name, {
						enumerable: true,
						configurable: true,
						writable: true,
						value: value
					} );
				}
			} );
		},

		fix: function( originalEvent ) {
			return originalEvent[ jQuery.expando ] ?
				originalEvent :
				new jQuery.Event( originalEvent );
		},

		special: {
			load: {

				// Prevent triggered image.load events from bubbling to window.load
				noBubble: true
			},
			click: {

				// Utilize native event to ensure correct state for checkable inputs
				setup: function( data ) {

					// For mutual compressibility with _default, replace `this` access with a local var.
					// `|| data` is dead code meant only to preserve the variable through minification.
					var el = this || data;

					// Claim the first handler
					if ( rcheckableType.test( el.type ) &&
						el.click && nodeName( el, "input" ) ) {

						// dataPriv.set( el, "click", ... )
						leverageNative( el, "click", true );
					}

					// Return false to allow normal processing in the caller
					return false;
				},
				trigger: function( data ) {

					// For mutual compressibility with _default, replace `this` access with a local var.
					// `|| data` is dead code meant only to preserve the variable through minification.
					var el = this || data;

					// Force setup before triggering a click
					if ( rcheckableType.test( el.type ) &&
						el.click && nodeName( el, "input" ) ) {

						leverageNative( el, "click" );
					}

					// Return non-false to allow normal event-path propagation
					return true;
				},

				// For cross-browser consistency, suppress native .click() on links
				// Also prevent it if we're currently inside a leveraged native-event stack
				_default: function( event ) {
					var target = event.target;
					return rcheckableType.test( target.type ) &&
						target.click && nodeName( target, "input" ) &&
						dataPriv.get( target, "click" ) ||
						nodeName( target, "a" );
				}
			},

			beforeunload: {
				postDispatch: function( event ) {

					// Support: Firefox 20+
					// Firefox doesn't alert if the returnValue field is not set.
					if ( event.result !== undefined && event.originalEvent ) {
						event.originalEvent.returnValue = event.result;
					}
				}
			}
		}
	};

	// Ensure the presence of an event listener that handles manually-triggered
	// synthetic events by interrupting progress until reinvoked in response to
	// *native* events that it fires directly, ensuring that state changes have
	// already occurred before other listeners are invoked.
	function leverageNative( el, type, isSetup ) {

		// Missing `isSetup` indicates a trigger call, which must force setup through jQuery.event.add
		if ( !isSetup ) {
			if ( dataPriv.get( el, type ) === undefined ) {
				jQuery.event.add( el, type, returnTrue );
			}
			return;
		}

		// Register the controller as a special universal handler for all event namespaces
		dataPriv.set( el, type, false );
		jQuery.event.add( el, type, {
			namespace: false,
			handler: function( event ) {
				var result,
					saved = dataPriv.get( this, type );

				if ( ( event.isTrigger & 1 ) && this[ type ] ) {

					// Interrupt processing of the outer synthetic .trigger()ed event
					if ( !saved ) {

						// Store arguments for use when handling the inner native event
						// There will always be at least one argument (an event object), so this array
						// will not be confused with a leftover capture object.
						saved = slice.call( arguments );
						dataPriv.set( this, type, saved );

						// Trigger the native event and capture its result
						this[ type ]();
						result = dataPriv.get( this, type );
						dataPriv.set( this, type, false );

						if ( saved !== result ) {

							// Cancel the outer synthetic event
							event.stopImmediatePropagation();
							event.preventDefault();

							return result;
						}

					// If this is an inner synthetic event for an event with a bubbling surrogate
					// (focus or blur), assume that the surrogate already propagated from triggering
					// the native event and prevent that from happening again here.
					// This technically gets the ordering wrong w.r.t. to `.trigger()` (in which the
					// bubbling surrogate propagates *after* the non-bubbling base), but that seems
					// less bad than duplication.
					} else if ( ( jQuery.event.special[ type ] || {} ).delegateType ) {
						event.stopPropagation();
					}

				// If this is a native event triggered above, everything is now in order
				// Fire an inner synthetic event with the original arguments
				} else if ( saved ) {

					// ...and capture the result
					dataPriv.set( this, type, jQuery.event.trigger(
						saved[ 0 ],
						saved.slice( 1 ),
						this
					) );

					// Abort handling of the native event by all jQuery handlers while allowing
					// native handlers on the same element to run. On target, this is achieved
					// by stopping immediate propagation just on the jQuery event. However,
					// the native event is re-wrapped by a jQuery one on each level of the
					// propagation so the only way to stop it for jQuery is to stop it for
					// everyone via native `stopPropagation()`. This is not a problem for
					// focus/blur which don't bubble, but it does also stop click on checkboxes
					// and radios. We accept this limitation.
					event.stopPropagation();
					event.isImmediatePropagationStopped = returnTrue;
				}
			}
		} );
	}

	jQuery.removeEvent = function( elem, type, handle ) {

		// This "if" is needed for plain objects
		if ( elem.removeEventListener ) {
			elem.removeEventListener( type, handle );
		}
	};

	jQuery.Event = function( src, props ) {

		// Allow instantiation without the 'new' keyword
		if ( !( this instanceof jQuery.Event ) ) {
			return new jQuery.Event( src, props );
		}

		// Event object
		if ( src && src.type ) {
			this.originalEvent = src;
			this.type = src.type;

			// Events bubbling up the document may have been marked as prevented
			// by a handler lower down the tree; reflect the correct value.
			this.isDefaultPrevented = src.defaultPrevented ||
					src.defaultPrevented === undefined &&

					// Support: Android <=2.3 only
					src.returnValue === false ?
				returnTrue :
				returnFalse;

			// Create target properties
			// Support: Safari <=6 - 7 only
			// Target should not be a text node (trac-504, trac-13143)
			this.target = ( src.target && src.target.nodeType === 3 ) ?
				src.target.parentNode :
				src.target;

			this.currentTarget = src.currentTarget;
			this.relatedTarget = src.relatedTarget;

		// Event type
		} else {
			this.type = src;
		}

		// Put explicitly provided properties onto the event object
		if ( props ) {
			jQuery.extend( this, props );
		}

		// Create a timestamp if incoming event doesn't have one
		this.timeStamp = src && src.timeStamp || Date.now();

		// Mark it as fixed
		this[ jQuery.expando ] = true;
	};

	// jQuery.Event is based on DOM3 Events as specified by the ECMAScript Language Binding
	// https://www.w3.org/TR/2003/WD-DOM-Level-3-Events-20030331/ecma-script-binding.html
	jQuery.Event.prototype = {
		constructor: jQuery.Event,
		isDefaultPrevented: returnFalse,
		isPropagationStopped: returnFalse,
		isImmediatePropagationStopped: returnFalse,
		isSimulated: false,

		preventDefault: function() {
			var e = this.originalEvent;

			this.isDefaultPrevented = returnTrue;

			if ( e && !this.isSimulated ) {
				e.preventDefault();
			}
		},
		stopPropagation: function() {
			var e = this.originalEvent;

			this.isPropagationStopped = returnTrue;

			if ( e && !this.isSimulated ) {
				e.stopPropagation();
			}
		},
		stopImmediatePropagation: function() {
			var e = this.originalEvent;

			this.isImmediatePropagationStopped = returnTrue;

			if ( e && !this.isSimulated ) {
				e.stopImmediatePropagation();
			}

			this.stopPropagation();
		}
	};

	// Includes all common event props including KeyEvent and MouseEvent specific props
	jQuery.each( {
		altKey: true,
		bubbles: true,
		cancelable: true,
		changedTouches: true,
		ctrlKey: true,
		detail: true,
		eventPhase: true,
		metaKey: true,
		pageX: true,
		pageY: true,
		shiftKey: true,
		view: true,
		"char": true,
		code: true,
		charCode: true,
		key: true,
		keyCode: true,
		button: true,
		buttons: true,
		clientX: true,
		clientY: true,
		offsetX: true,
		offsetY: true,
		pointerId: true,
		pointerType: true,
		screenX: true,
		screenY: true,
		targetTouches: true,
		toElement: true,
		touches: true,
		which: true
	}, jQuery.event.addProp );

	jQuery.each( { focus: "focusin", blur: "focusout" }, function( type, delegateType ) {

		function focusMappedHandler( nativeEvent ) {
			if ( document.documentMode ) {

				// Support: IE 11+
				// Attach a single focusin/focusout handler on the document while someone wants
				// focus/blur. This is because the former are synchronous in IE while the latter
				// are async. In other browsers, all those handlers are invoked synchronously.

				// `handle` from private data would already wrap the event, but we need
				// to change the `type` here.
				var handle = dataPriv.get( this, "handle" ),
					event = jQuery.event.fix( nativeEvent );
				event.type = nativeEvent.type === "focusin" ? "focus" : "blur";
				event.isSimulated = true;

				// First, handle focusin/focusout
				handle( nativeEvent );

				// ...then, handle focus/blur
				//
				// focus/blur don't bubble while focusin/focusout do; simulate the former by only
				// invoking the handler at the lower level.
				if ( event.target === event.currentTarget ) {

					// The setup part calls `leverageNative`, which, in turn, calls
					// `jQuery.event.add`, so event handle will already have been set
					// by this point.
					handle( event );
				}
			} else {

				// For non-IE browsers, attach a single capturing handler on the document
				// while someone wants focusin/focusout.
				jQuery.event.simulate( delegateType, nativeEvent.target,
					jQuery.event.fix( nativeEvent ) );
			}
		}

		jQuery.event.special[ type ] = {

			// Utilize native event if possible so blur/focus sequence is correct
			setup: function() {

				var attaches;

				// Claim the first handler
				// dataPriv.set( this, "focus", ... )
				// dataPriv.set( this, "blur", ... )
				leverageNative( this, type, true );

				if ( document.documentMode ) {

					// Support: IE 9 - 11+
					// We use the same native handler for focusin & focus (and focusout & blur)
					// so we need to coordinate setup & teardown parts between those events.
					// Use `delegateType` as the key as `type` is already used by `leverageNative`.
					attaches = dataPriv.get( this, delegateType );
					if ( !attaches ) {
						this.addEventListener( delegateType, focusMappedHandler );
					}
					dataPriv.set( this, delegateType, ( attaches || 0 ) + 1 );
				} else {

					// Return false to allow normal processing in the caller
					return false;
				}
			},
			trigger: function() {

				// Force setup before trigger
				leverageNative( this, type );

				// Return non-false to allow normal event-path propagation
				return true;
			},

			teardown: function() {
				var attaches;

				if ( document.documentMode ) {
					attaches = dataPriv.get( this, delegateType ) - 1;
					if ( !attaches ) {
						this.removeEventListener( delegateType, focusMappedHandler );
						dataPriv.remove( this, delegateType );
					} else {
						dataPriv.set( this, delegateType, attaches );
					}
				} else {

					// Return false to indicate standard teardown should be applied
					return false;
				}
			},

			// Suppress native focus or blur if we're currently inside
			// a leveraged native-event stack
			_default: function( event ) {
				return dataPriv.get( event.target, type );
			},

			delegateType: delegateType
		};

		// Support: Firefox <=44
		// Firefox doesn't have focus(in | out) events
		// Related ticket - https://bugzilla.mozilla.org/show_bug.cgi?id=687787
		//
		// Support: Chrome <=48 - 49, Safari <=9.0 - 9.1
		// focus(in | out) events fire after focus & blur events,
		// which is spec violation - http://www.w3.org/TR/DOM-Level-3-Events/#events-focusevent-event-order
		// Related ticket - https://bugs.chromium.org/p/chromium/issues/detail?id=449857
		//
		// Support: IE 9 - 11+
		// To preserve relative focusin/focus & focusout/blur event order guaranteed on the 3.x branch,
		// attach a single handler for both events in IE.
		jQuery.event.special[ delegateType ] = {
			setup: function() {

				// Handle: regular nodes (via `this.ownerDocument`), window
				// (via `this.document`) & document (via `this`).
				var doc = this.ownerDocument || this.document || this,
					dataHolder = document.documentMode ? this : doc,
					attaches = dataPriv.get( dataHolder, delegateType );

				// Support: IE 9 - 11+
				// We use the same native handler for focusin & focus (and focusout & blur)
				// so we need to coordinate setup & teardown parts between those events.
				// Use `delegateType` as the key as `type` is already used by `leverageNative`.
				if ( !attaches ) {
					if ( document.documentMode ) {
						this.addEventListener( delegateType, focusMappedHandler );
					} else {
						doc.addEventListener( type, focusMappedHandler, true );
					}
				}
				dataPriv.set( dataHolder, delegateType, ( attaches || 0 ) + 1 );
			},
			teardown: function() {
				var doc = this.ownerDocument || this.document || this,
					dataHolder = document.documentMode ? this : doc,
					attaches = dataPriv.get( dataHolder, delegateType ) - 1;

				if ( !attaches ) {
					if ( document.documentMode ) {
						this.removeEventListener( delegateType, focusMappedHandler );
					} else {
						doc.removeEventListener( type, focusMappedHandler, true );
					}
					dataPriv.remove( dataHolder, delegateType );
				} else {
					dataPriv.set( dataHolder, delegateType, attaches );
				}
			}
		};
	} );

	// Create mouseenter/leave events using mouseover/out and event-time checks
	// so that event delegation works in jQuery.
	// Do the same for pointerenter/pointerleave and pointerover/pointerout
	//
	// Support: Safari 7 only
	// Safari sends mouseenter too often; see:
	// https://bugs.chromium.org/p/chromium/issues/detail?id=470258
	// for the description of the bug (it existed in older Chrome versions as well).
	jQuery.each( {
		mouseenter: "mouseover",
		mouseleave: "mouseout",
		pointerenter: "pointerover",
		pointerleave: "pointerout"
	}, function( orig, fix ) {
		jQuery.event.special[ orig ] = {
			delegateType: fix,
			bindType: fix,

			handle: function( event ) {
				var ret,
					target = this,
					related = event.relatedTarget,
					handleObj = event.handleObj;

				// For mouseenter/leave call the handler if related is outside the target.
				// NB: No relatedTarget if the mouse left/entered the browser window
				if ( !related || ( related !== target && !jQuery.contains( target, related ) ) ) {
					event.type = handleObj.origType;
					ret = handleObj.handler.apply( this, arguments );
					event.type = fix;
				}
				return ret;
			}
		};
	} );

	jQuery.fn.extend( {

		on: function( types, selector, data, fn ) {
			return on( this, types, selector, data, fn );
		},
		one: function( types, selector, data, fn ) {
			return on( this, types, selector, data, fn, 1 );
		},
		off: function( types, selector, fn ) {
			var handleObj, type;
			if ( types && types.preventDefault && types.handleObj ) {

				// ( event )  dispatched jQuery.Event
				handleObj = types.handleObj;
				jQuery( types.delegateTarget ).off(
					handleObj.namespace ?
						handleObj.origType + "." + handleObj.namespace :
						handleObj.origType,
					handleObj.selector,
					handleObj.handler
				);
				return this;
			}
			if ( typeof types === "object" ) {

				// ( types-object [, selector] )
				for ( type in types ) {
					this.off( type, selector, types[ type ] );
				}
				return this;
			}
			if ( selector === false || typeof selector === "function" ) {

				// ( types [, fn] )
				fn = selector;
				selector = undefined;
			}
			if ( fn === false ) {
				fn = returnFalse;
			}
			return this.each( function() {
				jQuery.event.remove( this, types, fn, selector );
			} );
		}
	} );


	var

		// Support: IE <=10 - 11, Edge 12 - 13 only
		// In IE/Edge using regex groups here causes severe slowdowns.
		// See https://connect.microsoft.com/IE/feedback/details/1736512/
		rnoInnerhtml = /<script|<style|<link/i,

		// checked="checked" or checked
		rchecked = /checked\s*(?:[^=]|=\s*.checked.)/i,

		rcleanScript = /^\s*<!\[CDATA\[|\]\]>\s*$/g;

	// Prefer a tbody over its parent table for containing new rows
	function manipulationTarget( elem, content ) {
		if ( nodeName( elem, "table" ) &&
			nodeName( content.nodeType !== 11 ? content : content.firstChild, "tr" ) ) {

			return jQuery( elem ).children( "tbody" )[ 0 ] || elem;
		}

		return elem;
	}

	// Replace/restore the type attribute of script elements for safe DOM manipulation
	function disableScript( elem ) {
		elem.type = ( elem.getAttribute( "type" ) !== null ) + "/" + elem.type;
		return elem;
	}
	function restoreScript( elem ) {
		if ( ( elem.type || "" ).slice( 0, 5 ) === "true/" ) {
			elem.type = elem.type.slice( 5 );
		} else {
			elem.removeAttribute( "type" );
		}

		return elem;
	}

	function cloneCopyEvent( src, dest ) {
		var i, l, type, pdataOld, udataOld, udataCur, events;

		if ( dest.nodeType !== 1 ) {
			return;
		}

		// 1. Copy private data: events, handlers, etc.
		if ( dataPriv.hasData( src ) ) {
			pdataOld = dataPriv.get( src );
			events = pdataOld.events;

			if ( events ) {
				dataPriv.remove( dest, "handle events" );

				for ( type in events ) {
					for ( i = 0, l = events[ type ].length; i < l; i++ ) {
						jQuery.event.add( dest, type, events[ type ][ i ] );
					}
				}
			}
		}

		// 2. Copy user data
		if ( dataUser.hasData( src ) ) {
			udataOld = dataUser.access( src );
			udataCur = jQuery.extend( {}, udataOld );

			dataUser.set( dest, udataCur );
		}
	}

	// Fix IE bugs, see support tests
	function fixInput( src, dest ) {
		var nodeName = dest.nodeName.toLowerCase();

		// Fails to persist the checked state of a cloned checkbox or radio button.
		if ( nodeName === "input" && rcheckableType.test( src.type ) ) {
			dest.checked = src.checked;

		// Fails to return the selected option to the default selected state when cloning options
		} else if ( nodeName === "input" || nodeName === "textarea" ) {
			dest.defaultValue = src.defaultValue;
		}
	}

	function domManip( collection, args, callback, ignored ) {

		// Flatten any nested arrays
		args = flat( args );

		var fragment, first, scripts, hasScripts, node, doc,
			i = 0,
			l = collection.length,
			iNoClone = l - 1,
			value = args[ 0 ],
			valueIsFunction = isFunction( value );

		// We can't cloneNode fragments that contain checked, in WebKit
		if ( valueIsFunction ||
				( l > 1 && typeof value === "string" &&
					!support.checkClone && rchecked.test( value ) ) ) {
			return collection.each( function( index ) {
				var self = collection.eq( index );
				if ( valueIsFunction ) {
					args[ 0 ] = value.call( this, index, self.html() );
				}
				domManip( self, args, callback, ignored );
			} );
		}

		if ( l ) {
			fragment = buildFragment( args, collection[ 0 ].ownerDocument, false, collection, ignored );
			first = fragment.firstChild;

			if ( fragment.childNodes.length === 1 ) {
				fragment = first;
			}

			// Require either new content or an interest in ignored elements to invoke the callback
			if ( first || ignored ) {
				scripts = jQuery.map( getAll( fragment, "script" ), disableScript );
				hasScripts = scripts.length;

				// Use the original fragment for the last item
				// instead of the first because it can end up
				// being emptied incorrectly in certain situations (trac-8070).
				for ( ; i < l; i++ ) {
					node = fragment;

					if ( i !== iNoClone ) {
						node = jQuery.clone( node, true, true );

						// Keep references to cloned scripts for later restoration
						if ( hasScripts ) {

							// Support: Android <=4.0 only, PhantomJS 1 only
							// push.apply(_, arraylike) throws on ancient WebKit
							jQuery.merge( scripts, getAll( node, "script" ) );
						}
					}

					callback.call( collection[ i ], node, i );
				}

				if ( hasScripts ) {
					doc = scripts[ scripts.length - 1 ].ownerDocument;

					// Re-enable scripts
					jQuery.map( scripts, restoreScript );

					// Evaluate executable scripts on first document insertion
					for ( i = 0; i < hasScripts; i++ ) {
						node = scripts[ i ];
						if ( rscriptType.test( node.type || "" ) &&
							!dataPriv.access( node, "globalEval" ) &&
							jQuery.contains( doc, node ) ) {

							if ( node.src && ( node.type || "" ).toLowerCase()  !== "module" ) {

								// Optional AJAX dependency, but won't run scripts if not present
								if ( jQuery._evalUrl && !node.noModule ) {
									jQuery._evalUrl( node.src, {
										nonce: node.nonce || node.getAttribute( "nonce" )
									}, doc );
								}
							} else {

								// Unwrap a CDATA section containing script contents. This shouldn't be
								// needed as in XML documents they're already not visible when
								// inspecting element contents and in HTML documents they have no
								// meaning but we're preserving that logic for backwards compatibility.
								// This will be removed completely in 4.0. See gh-4904.
								DOMEval( node.textContent.replace( rcleanScript, "" ), node, doc );
							}
						}
					}
				}
			}
		}

		return collection;
	}

	function remove( elem, selector, keepData ) {
		var node,
			nodes = selector ? jQuery.filter( selector, elem ) : elem,
			i = 0;

		for ( ; ( node = nodes[ i ] ) != null; i++ ) {
			if ( !keepData && node.nodeType === 1 ) {
				jQuery.cleanData( getAll( node ) );
			}

			if ( node.parentNode ) {
				if ( keepData && isAttached( node ) ) {
					setGlobalEval( getAll( node, "script" ) );
				}
				node.parentNode.removeChild( node );
			}
		}

		return elem;
	}

	jQuery.extend( {
		htmlPrefilter: function( html ) {
			return html;
		},

		clone: function( elem, dataAndEvents, deepDataAndEvents ) {
			var i, l, srcElements, destElements,
				clone = elem.cloneNode( true ),
				inPage = isAttached( elem );

			// Fix IE cloning issues
			if ( !support.noCloneChecked && ( elem.nodeType === 1 || elem.nodeType === 11 ) &&
					!jQuery.isXMLDoc( elem ) ) {

				// We eschew jQuery#find here for performance reasons:
				// https://jsperf.com/getall-vs-sizzle/2
				destElements = getAll( clone );
				srcElements = getAll( elem );

				for ( i = 0, l = srcElements.length; i < l; i++ ) {
					fixInput( srcElements[ i ], destElements[ i ] );
				}
			}

			// Copy the events from the original to the clone
			if ( dataAndEvents ) {
				if ( deepDataAndEvents ) {
					srcElements = srcElements || getAll( elem );
					destElements = destElements || getAll( clone );

					for ( i = 0, l = srcElements.length; i < l; i++ ) {
						cloneCopyEvent( srcElements[ i ], destElements[ i ] );
					}
				} else {
					cloneCopyEvent( elem, clone );
				}
			}

			// Preserve script evaluation history
			destElements = getAll( clone, "script" );
			if ( destElements.length > 0 ) {
				setGlobalEval( destElements, !inPage && getAll( elem, "script" ) );
			}

			// Return the cloned set
			return clone;
		},

		cleanData: function( elems ) {
			var data, elem, type,
				special = jQuery.event.special,
				i = 0;

			for ( ; ( elem = elems[ i ] ) !== undefined; i++ ) {
				if ( acceptData( elem ) ) {
					if ( ( data = elem[ dataPriv.expando ] ) ) {
						if ( data.events ) {
							for ( type in data.events ) {
								if ( special[ type ] ) {
									jQuery.event.remove( elem, type );

								// This is a shortcut to avoid jQuery.event.remove's overhead
								} else {
									jQuery.removeEvent( elem, type, data.handle );
								}
							}
						}

						// Support: Chrome <=35 - 45+
						// Assign undefined instead of using delete, see Data#remove
						elem[ dataPriv.expando ] = undefined;
					}
					if ( elem[ dataUser.expando ] ) {

						// Support: Chrome <=35 - 45+
						// Assign undefined instead of using delete, see Data#remove
						elem[ dataUser.expando ] = undefined;
					}
				}
			}
		}
	} );

	jQuery.fn.extend( {
		detach: function( selector ) {
			return remove( this, selector, true );
		},

		remove: function( selector ) {
			return remove( this, selector );
		},

		text: function( value ) {
			return access( this, function( value ) {
				return value === undefined ?
					jQuery.text( this ) :
					this.empty().each( function() {
						if ( this.nodeType === 1 || this.nodeType === 11 || this.nodeType === 9 ) {
							this.textContent = value;
						}
					} );
			}, null, value, arguments.length );
		},

		append: function() {
			return domManip( this, arguments, function( elem ) {
				if ( this.nodeType === 1 || this.nodeType === 11 || this.nodeType === 9 ) {
					var target = manipulationTarget( this, elem );
					target.appendChild( elem );
				}
			} );
		},

		prepend: function() {
			return domManip( this, arguments, function( elem ) {
				if ( this.nodeType === 1 || this.nodeType === 11 || this.nodeType === 9 ) {
					var target = manipulationTarget( this, elem );
					target.insertBefore( elem, target.firstChild );
				}
			} );
		},

		before: function() {
			return domManip( this, arguments, function( elem ) {
				if ( this.parentNode ) {
					this.parentNode.insertBefore( elem, this );
				}
			} );
		},

		after: function() {
			return domManip( this, arguments, function( elem ) {
				if ( this.parentNode ) {
					this.parentNode.insertBefore( elem, this.nextSibling );
				}
			} );
		},

		empty: function() {
			var elem,
				i = 0;

			for ( ; ( elem = this[ i ] ) != null; i++ ) {
				if ( elem.nodeType === 1 ) {

					// Prevent memory leaks
					jQuery.cleanData( getAll( elem, false ) );

					// Remove any remaining nodes
					elem.textContent = "";
				}
			}

			return this;
		},

		clone: function( dataAndEvents, deepDataAndEvents ) {
			dataAndEvents = dataAndEvents == null ? false : dataAndEvents;
			deepDataAndEvents = deepDataAndEvents == null ? dataAndEvents : deepDataAndEvents;

			return this.map( function() {
				return jQuery.clone( this, dataAndEvents, deepDataAndEvents );
			} );
		},

		html: function( value ) {
			return access( this, function( value ) {
				var elem = this[ 0 ] || {},
					i = 0,
					l = this.length;

				if ( value === undefined && elem.nodeType === 1 ) {
					return elem.innerHTML;
				}

				// See if we can take a shortcut and just use innerHTML
				if ( typeof value === "string" && !rnoInnerhtml.test( value ) &&
					!wrapMap[ ( rtagName.exec( value ) || [ "", "" ] )[ 1 ].toLowerCase() ] ) {

					value = jQuery.htmlPrefilter( value );

					try {
						for ( ; i < l; i++ ) {
							elem = this[ i ] || {};

							// Remove element nodes and prevent memory leaks
							if ( elem.nodeType === 1 ) {
								jQuery.cleanData( getAll( elem, false ) );
								elem.innerHTML = value;
							}
						}

						elem = 0;

					// If using innerHTML throws an exception, use the fallback method
					} catch ( e ) {}
				}

				if ( elem ) {
					this.empty().append( value );
				}
			}, null, value, arguments.length );
		},

		replaceWith: function() {
			var ignored = [];

			// Make the changes, replacing each non-ignored context element with the new content
			return domManip( this, arguments, function( elem ) {
				var parent = this.parentNode;

				if ( jQuery.inArray( this, ignored ) < 0 ) {
					jQuery.cleanData( getAll( this ) );
					if ( parent ) {
						parent.replaceChild( elem, this );
					}
				}

			// Force callback invocation
			}, ignored );
		}
	} );

	jQuery.each( {
		appendTo: "append",
		prependTo: "prepend",
		insertBefore: "before",
		insertAfter: "after",
		replaceAll: "replaceWith"
	}, function( name, original ) {
		jQuery.fn[ name ] = function( selector ) {
			var elems,
				ret = [],
				insert = jQuery( selector ),
				last = insert.length - 1,
				i = 0;

			for ( ; i <= last; i++ ) {
				elems = i === last ? this : this.clone( true );
				jQuery( insert[ i ] )[ original ]( elems );

				// Support: Android <=4.0 only, PhantomJS 1 only
				// .get() because push.apply(_, arraylike) throws on ancient WebKit
				push.apply( ret, elems.get() );
			}

			return this.pushStack( ret );
		};
	} );
	var rnumnonpx = new RegExp( "^(" + pnum + ")(?!px)[a-z%]+$", "i" );

	var rcustomProp = /^--/;


	var getStyles = function( elem ) {

			// Support: IE <=11 only, Firefox <=30 (trac-15098, trac-14150)
			// IE throws on elements created in popups
			// FF meanwhile throws on frame elements through "defaultView.getComputedStyle"
			var view = elem.ownerDocument.defaultView;

			if ( !view || !view.opener ) {
				view = window;
			}

			return view.getComputedStyle( elem );
		};

	var swap = function( elem, options, callback ) {
		var ret, name,
			old = {};

		// Remember the old values, and insert the new ones
		for ( name in options ) {
			old[ name ] = elem.style[ name ];
			elem.style[ name ] = options[ name ];
		}

		ret = callback.call( elem );

		// Revert the old values
		for ( name in options ) {
			elem.style[ name ] = old[ name ];
		}

		return ret;
	};


	var rboxStyle = new RegExp( cssExpand.join( "|" ), "i" );



	( function() {

		// Executing both pixelPosition & boxSizingReliable tests require only one layout
		// so they're executed at the same time to save the second computation.
		function computeStyleTests() {

			// This is a singleton, we need to execute it only once
			if ( !div ) {
				return;
			}

			container.style.cssText = "position:absolute;left:-11111px;width:60px;" +
				"margin-top:1px;padding:0;border:0";
			div.style.cssText =
				"position:relative;display:block;box-sizing:border-box;overflow:scroll;" +
				"margin:auto;border:1px;padding:1px;" +
				"width:60%;top:1%";
			documentElement.appendChild( container ).appendChild( div );

			var divStyle = window.getComputedStyle( div );
			pixelPositionVal = divStyle.top !== "1%";

			// Support: Android 4.0 - 4.3 only, Firefox <=3 - 44
			reliableMarginLeftVal = roundPixelMeasures( divStyle.marginLeft ) === 12;

			// Support: Android 4.0 - 4.3 only, Safari <=9.1 - 10.1, iOS <=7.0 - 9.3
			// Some styles come back with percentage values, even though they shouldn't
			div.style.right = "60%";
			pixelBoxStylesVal = roundPixelMeasures( divStyle.right ) === 36;

			// Support: IE 9 - 11 only
			// Detect misreporting of content dimensions for box-sizing:border-box elements
			boxSizingReliableVal = roundPixelMeasures( divStyle.width ) === 36;

			// Support: IE 9 only
			// Detect overflow:scroll screwiness (gh-3699)
			// Support: Chrome <=64
			// Don't get tricked when zoom affects offsetWidth (gh-4029)
			div.style.position = "absolute";
			scrollboxSizeVal = roundPixelMeasures( div.offsetWidth / 3 ) === 12;

			documentElement.removeChild( container );

			// Nullify the div so it wouldn't be stored in the memory and
			// it will also be a sign that checks already performed
			div = null;
		}

		function roundPixelMeasures( measure ) {
			return Math.round( parseFloat( measure ) );
		}

		var pixelPositionVal, boxSizingReliableVal, scrollboxSizeVal, pixelBoxStylesVal,
			reliableTrDimensionsVal, reliableMarginLeftVal,
			container = document.createElement( "div" ),
			div = document.createElement( "div" );

		// Finish early in limited (non-browser) environments
		if ( !div.style ) {
			return;
		}

		// Support: IE <=9 - 11 only
		// Style of cloned element affects source element cloned (trac-8908)
		div.style.backgroundClip = "content-box";
		div.cloneNode( true ).style.backgroundClip = "";
		support.clearCloneStyle = div.style.backgroundClip === "content-box";

		jQuery.extend( support, {
			boxSizingReliable: function() {
				computeStyleTests();
				return boxSizingReliableVal;
			},
			pixelBoxStyles: function() {
				computeStyleTests();
				return pixelBoxStylesVal;
			},
			pixelPosition: function() {
				computeStyleTests();
				return pixelPositionVal;
			},
			reliableMarginLeft: function() {
				computeStyleTests();
				return reliableMarginLeftVal;
			},
			scrollboxSize: function() {
				computeStyleTests();
				return scrollboxSizeVal;
			},

			// Support: IE 9 - 11+, Edge 15 - 18+
			// IE/Edge misreport `getComputedStyle` of table rows with width/height
			// set in CSS while `offset*` properties report correct values.
			// Behavior in IE 9 is more subtle than in newer versions & it passes
			// some versions of this test; make sure not to make it pass there!
			//
			// Support: Firefox 70+
			// Only Firefox includes border widths
			// in computed dimensions. (gh-4529)
			reliableTrDimensions: function() {
				var table, tr, trChild, trStyle;
				if ( reliableTrDimensionsVal == null ) {
					table = document.createElement( "table" );
					tr = document.createElement( "tr" );
					trChild = document.createElement( "div" );

					table.style.cssText = "position:absolute;left:-11111px;border-collapse:separate";
					tr.style.cssText = "box-sizing:content-box;border:1px solid";

					// Support: Chrome 86+
					// Height set through cssText does not get applied.
					// Computed height then comes back as 0.
					tr.style.height = "1px";
					trChild.style.height = "9px";

					// Support: Android 8 Chrome 86+
					// In our bodyBackground.html iframe,
					// display for all div elements is set to "inline",
					// which causes a problem only in Android 8 Chrome 86.
					// Ensuring the div is `display: block`
					// gets around this issue.
					trChild.style.display = "block";

					documentElement
						.appendChild( table )
						.appendChild( tr )
						.appendChild( trChild );

					trStyle = window.getComputedStyle( tr );
					reliableTrDimensionsVal = ( parseInt( trStyle.height, 10 ) +
						parseInt( trStyle.borderTopWidth, 10 ) +
						parseInt( trStyle.borderBottomWidth, 10 ) ) === tr.offsetHeight;

					documentElement.removeChild( table );
				}
				return reliableTrDimensionsVal;
			}
		} );
	} )();


	function curCSS( elem, name, computed ) {
		var width, minWidth, maxWidth, ret,
			isCustomProp = rcustomProp.test( name ),

			// Support: Firefox 51+
			// Retrieving style before computed somehow
			// fixes an issue with getting wrong values
			// on detached elements
			style = elem.style;

		computed = computed || getStyles( elem );

		// getPropertyValue is needed for:
		//   .css('filter') (IE 9 only, trac-12537)
		//   .css('--customProperty) (gh-3144)
		if ( computed ) {

			// Support: IE <=9 - 11+
			// IE only supports `"float"` in `getPropertyValue`; in computed styles
			// it's only available as `"cssFloat"`. We no longer modify properties
			// sent to `.css()` apart from camelCasing, so we need to check both.
			// Normally, this would create difference in behavior: if
			// `getPropertyValue` returns an empty string, the value returned
			// by `.css()` would be `undefined`. This is usually the case for
			// disconnected elements. However, in IE even disconnected elements
			// with no styles return `"none"` for `getPropertyValue( "float" )`
			ret = computed.getPropertyValue( name ) || computed[ name ];

			if ( isCustomProp && ret ) {

				// Support: Firefox 105+, Chrome <=105+
				// Spec requires trimming whitespace for custom properties (gh-4926).
				// Firefox only trims leading whitespace. Chrome just collapses
				// both leading & trailing whitespace to a single space.
				//
				// Fall back to `undefined` if empty string returned.
				// This collapses a missing definition with property defined
				// and set to an empty string but there's no standard API
				// allowing us to differentiate them without a performance penalty
				// and returning `undefined` aligns with older jQuery.
				//
				// rtrimCSS treats U+000D CARRIAGE RETURN and U+000C FORM FEED
				// as whitespace while CSS does not, but this is not a problem
				// because CSS preprocessing replaces them with U+000A LINE FEED
				// (which *is* CSS whitespace)
				// https://www.w3.org/TR/css-syntax-3/#input-preprocessing
				ret = ret.replace( rtrimCSS, "$1" ) || undefined;
			}

			if ( ret === "" && !isAttached( elem ) ) {
				ret = jQuery.style( elem, name );
			}

			// A tribute to the "awesome hack by Dean Edwards"
			// Android Browser returns percentage for some values,
			// but width seems to be reliably pixels.
			// This is against the CSSOM draft spec:
			// https://drafts.csswg.org/cssom/#resolved-values
			if ( !support.pixelBoxStyles() && rnumnonpx.test( ret ) && rboxStyle.test( name ) ) {

				// Remember the original values
				width = style.width;
				minWidth = style.minWidth;
				maxWidth = style.maxWidth;

				// Put in the new values to get a computed value out
				style.minWidth = style.maxWidth = style.width = ret;
				ret = computed.width;

				// Revert the changed values
				style.width = width;
				style.minWidth = minWidth;
				style.maxWidth = maxWidth;
			}
		}

		return ret !== undefined ?

			// Support: IE <=9 - 11 only
			// IE returns zIndex value as an integer.
			ret + "" :
			ret;
	}


	function addGetHookIf( conditionFn, hookFn ) {

		// Define the hook, we'll check on the first run if it's really needed.
		return {
			get: function() {
				if ( conditionFn() ) {

					// Hook not needed (or it's not possible to use it due
					// to missing dependency), remove it.
					delete this.get;
					return;
				}

				// Hook needed; redefine it so that the support test is not executed again.
				return ( this.get = hookFn ).apply( this, arguments );
			}
		};
	}


	var cssPrefixes = [ "Webkit", "Moz", "ms" ],
		emptyStyle = document.createElement( "div" ).style,
		vendorProps = {};

	// Return a vendor-prefixed property or undefined
	function vendorPropName( name ) {

		// Check for vendor prefixed names
		var capName = name[ 0 ].toUpperCase() + name.slice( 1 ),
			i = cssPrefixes.length;

		while ( i-- ) {
			name = cssPrefixes[ i ] + capName;
			if ( name in emptyStyle ) {
				return name;
			}
		}
	}

	// Return a potentially-mapped jQuery.cssProps or vendor prefixed property
	function finalPropName( name ) {
		var final = jQuery.cssProps[ name ] || vendorProps[ name ];

		if ( final ) {
			return final;
		}
		if ( name in emptyStyle ) {
			return name;
		}
		return vendorProps[ name ] = vendorPropName( name ) || name;
	}


	var

		// Swappable if display is none or starts with table
		// except "table", "table-cell", or "table-caption"
		// See here for display values: https://developer.mozilla.org/en-US/docs/CSS/display
		rdisplayswap = /^(none|table(?!-c[ea]).+)/,
		cssShow = { position: "absolute", visibility: "hidden", display: "block" },
		cssNormalTransform = {
			letterSpacing: "0",
			fontWeight: "400"
		};

	function setPositiveNumber( _elem, value, subtract ) {

		// Any relative (+/-) values have already been
		// normalized at this point
		var matches = rcssNum.exec( value );
		return matches ?

			// Guard against undefined "subtract", e.g., when used as in cssHooks
			Math.max( 0, matches[ 2 ] - ( subtract || 0 ) ) + ( matches[ 3 ] || "px" ) :
			value;
	}

	function boxModelAdjustment( elem, dimension, box, isBorderBox, styles, computedVal ) {
		var i = dimension === "width" ? 1 : 0,
			extra = 0,
			delta = 0,
			marginDelta = 0;

		// Adjustment may not be necessary
		if ( box === ( isBorderBox ? "border" : "content" ) ) {
			return 0;
		}

		for ( ; i < 4; i += 2 ) {

			// Both box models exclude margin
			// Count margin delta separately to only add it after scroll gutter adjustment.
			// This is needed to make negative margins work with `outerHeight( true )` (gh-3982).
			if ( box === "margin" ) {
				marginDelta += jQuery.css( elem, box + cssExpand[ i ], true, styles );
			}

			// If we get here with a content-box, we're seeking "padding" or "border" or "margin"
			if ( !isBorderBox ) {

				// Add padding
				delta += jQuery.css( elem, "padding" + cssExpand[ i ], true, styles );

				// For "border" or "margin", add border
				if ( box !== "padding" ) {
					delta += jQuery.css( elem, "border" + cssExpand[ i ] + "Width", true, styles );

				// But still keep track of it otherwise
				} else {
					extra += jQuery.css( elem, "border" + cssExpand[ i ] + "Width", true, styles );
				}

			// If we get here with a border-box (content + padding + border), we're seeking "content" or
			// "padding" or "margin"
			} else {

				// For "content", subtract padding
				if ( box === "content" ) {
					delta -= jQuery.css( elem, "padding" + cssExpand[ i ], true, styles );
				}

				// For "content" or "padding", subtract border
				if ( box !== "margin" ) {
					delta -= jQuery.css( elem, "border" + cssExpand[ i ] + "Width", true, styles );
				}
			}
		}

		// Account for positive content-box scroll gutter when requested by providing computedVal
		if ( !isBorderBox && computedVal >= 0 ) {

			// offsetWidth/offsetHeight is a rounded sum of content, padding, scroll gutter, and border
			// Assuming integer scroll gutter, subtract the rest and round down
			delta += Math.max( 0, Math.ceil(
				elem[ "offset" + dimension[ 0 ].toUpperCase() + dimension.slice( 1 ) ] -
				computedVal -
				delta -
				extra -
				0.5

			// If offsetWidth/offsetHeight is unknown, then we can't determine content-box scroll gutter
			// Use an explicit zero to avoid NaN (gh-3964)
			) ) || 0;
		}

		return delta + marginDelta;
	}

	function getWidthOrHeight( elem, dimension, extra ) {

		// Start with computed style
		var styles = getStyles( elem ),

			// To avoid forcing a reflow, only fetch boxSizing if we need it (gh-4322).
			// Fake content-box until we know it's needed to know the true value.
			boxSizingNeeded = !support.boxSizingReliable() || extra,
			isBorderBox = boxSizingNeeded &&
				jQuery.css( elem, "boxSizing", false, styles ) === "border-box",
			valueIsBorderBox = isBorderBox,

			val = curCSS( elem, dimension, styles ),
			offsetProp = "offset" + dimension[ 0 ].toUpperCase() + dimension.slice( 1 );

		// Support: Firefox <=54
		// Return a confounding non-pixel value or feign ignorance, as appropriate.
		if ( rnumnonpx.test( val ) ) {
			if ( !extra ) {
				return val;
			}
			val = "auto";
		}


		// Support: IE 9 - 11 only
		// Use offsetWidth/offsetHeight for when box sizing is unreliable.
		// In those cases, the computed value can be trusted to be border-box.
		if ( ( !support.boxSizingReliable() && isBorderBox ||

			// Support: IE 10 - 11+, Edge 15 - 18+
			// IE/Edge misreport `getComputedStyle` of table rows with width/height
			// set in CSS while `offset*` properties report correct values.
			// Interestingly, in some cases IE 9 doesn't suffer from this issue.
			!support.reliableTrDimensions() && nodeName( elem, "tr" ) ||

			// Fall back to offsetWidth/offsetHeight when value is "auto"
			// This happens for inline elements with no explicit setting (gh-3571)
			val === "auto" ||

			// Support: Android <=4.1 - 4.3 only
			// Also use offsetWidth/offsetHeight for misreported inline dimensions (gh-3602)
			!parseFloat( val ) && jQuery.css( elem, "display", false, styles ) === "inline" ) &&

			// Make sure the element is visible & connected
			elem.getClientRects().length ) {

			isBorderBox = jQuery.css( elem, "boxSizing", false, styles ) === "border-box";

			// Where available, offsetWidth/offsetHeight approximate border box dimensions.
			// Where not available (e.g., SVG), assume unreliable box-sizing and interpret the
			// retrieved value as a content box dimension.
			valueIsBorderBox = offsetProp in elem;
			if ( valueIsBorderBox ) {
				val = elem[ offsetProp ];
			}
		}

		// Normalize "" and auto
		val = parseFloat( val ) || 0;

		// Adjust for the element's box model
		return ( val +
			boxModelAdjustment(
				elem,
				dimension,
				extra || ( isBorderBox ? "border" : "content" ),
				valueIsBorderBox,
				styles,

				// Provide the current computed size to request scroll gutter calculation (gh-3589)
				val
			)
		) + "px";
	}

	jQuery.extend( {

		// Add in style property hooks for overriding the default
		// behavior of getting and setting a style property
		cssHooks: {
			opacity: {
				get: function( elem, computed ) {
					if ( computed ) {

						// We should always get a number back from opacity
						var ret = curCSS( elem, "opacity" );
						return ret === "" ? "1" : ret;
					}
				}
			}
		},

		// Don't automatically add "px" to these possibly-unitless properties
		cssNumber: {
			animationIterationCount: true,
			aspectRatio: true,
			borderImageSlice: true,
			columnCount: true,
			flexGrow: true,
			flexShrink: true,
			fontWeight: true,
			gridArea: true,
			gridColumn: true,
			gridColumnEnd: true,
			gridColumnStart: true,
			gridRow: true,
			gridRowEnd: true,
			gridRowStart: true,
			lineHeight: true,
			opacity: true,
			order: true,
			orphans: true,
			scale: true,
			widows: true,
			zIndex: true,
			zoom: true,

			// SVG-related
			fillOpacity: true,
			floodOpacity: true,
			stopOpacity: true,
			strokeMiterlimit: true,
			strokeOpacity: true
		},

		// Add in properties whose names you wish to fix before
		// setting or getting the value
		cssProps: {},

		// Get and set the style property on a DOM Node
		style: function( elem, name, value, extra ) {

			// Don't set styles on text and comment nodes
			if ( !elem || elem.nodeType === 3 || elem.nodeType === 8 || !elem.style ) {
				return;
			}

			// Make sure that we're working with the right name
			var ret, type, hooks,
				origName = camelCase( name ),
				isCustomProp = rcustomProp.test( name ),
				style = elem.style;

			// Make sure that we're working with the right name. We don't
			// want to query the value if it is a CSS custom property
			// since they are user-defined.
			if ( !isCustomProp ) {
				name = finalPropName( origName );
			}

			// Gets hook for the prefixed version, then unprefixed version
			hooks = jQuery.cssHooks[ name ] || jQuery.cssHooks[ origName ];

			// Check if we're setting a value
			if ( value !== undefined ) {
				type = typeof value;

				// Convert "+=" or "-=" to relative numbers (trac-7345)
				if ( type === "string" && ( ret = rcssNum.exec( value ) ) && ret[ 1 ] ) {
					value = adjustCSS( elem, name, ret );

					// Fixes bug trac-9237
					type = "number";
				}

				// Make sure that null and NaN values aren't set (trac-7116)
				if ( value == null || value !== value ) {
					return;
				}

				// If a number was passed in, add the unit (except for certain CSS properties)
				// The isCustomProp check can be removed in jQuery 4.0 when we only auto-append
				// "px" to a few hardcoded values.
				if ( type === "number" && !isCustomProp ) {
					value += ret && ret[ 3 ] || ( jQuery.cssNumber[ origName ] ? "" : "px" );
				}

				// background-* props affect original clone's values
				if ( !support.clearCloneStyle && value === "" && name.indexOf( "background" ) === 0 ) {
					style[ name ] = "inherit";
				}

				// If a hook was provided, use that value, otherwise just set the specified value
				if ( !hooks || !( "set" in hooks ) ||
					( value = hooks.set( elem, value, extra ) ) !== undefined ) {

					if ( isCustomProp ) {
						style.setProperty( name, value );
					} else {
						style[ name ] = value;
					}
				}

			} else {

				// If a hook was provided get the non-computed value from there
				if ( hooks && "get" in hooks &&
					( ret = hooks.get( elem, false, extra ) ) !== undefined ) {

					return ret;
				}

				// Otherwise just get the value from the style object
				return style[ name ];
			}
		},

		css: function( elem, name, extra, styles ) {
			var val, num, hooks,
				origName = camelCase( name ),
				isCustomProp = rcustomProp.test( name );

			// Make sure that we're working with the right name. We don't
			// want to modify the value if it is a CSS custom property
			// since they are user-defined.
			if ( !isCustomProp ) {
				name = finalPropName( origName );
			}

			// Try prefixed name followed by the unprefixed name
			hooks = jQuery.cssHooks[ name ] || jQuery.cssHooks[ origName ];

			// If a hook was provided get the computed value from there
			if ( hooks && "get" in hooks ) {
				val = hooks.get( elem, true, extra );
			}

			// Otherwise, if a way to get the computed value exists, use that
			if ( val === undefined ) {
				val = curCSS( elem, name, styles );
			}

			// Convert "normal" to computed value
			if ( val === "normal" && name in cssNormalTransform ) {
				val = cssNormalTransform[ name ];
			}

			// Make numeric if forced or a qualifier was provided and val looks numeric
			if ( extra === "" || extra ) {
				num = parseFloat( val );
				return extra === true || isFinite( num ) ? num || 0 : val;
			}

			return val;
		}
	} );

	jQuery.each( [ "height", "width" ], function( _i, dimension ) {
		jQuery.cssHooks[ dimension ] = {
			get: function( elem, computed, extra ) {
				if ( computed ) {

					// Certain elements can have dimension info if we invisibly show them
					// but it must have a current display style that would benefit
					return rdisplayswap.test( jQuery.css( elem, "display" ) ) &&

						// Support: Safari 8+
						// Table columns in Safari have non-zero offsetWidth & zero
						// getBoundingClientRect().width unless display is changed.
						// Support: IE <=11 only
						// Running getBoundingClientRect on a disconnected node
						// in IE throws an error.
						( !elem.getClientRects().length || !elem.getBoundingClientRect().width ) ?
						swap( elem, cssShow, function() {
							return getWidthOrHeight( elem, dimension, extra );
						} ) :
						getWidthOrHeight( elem, dimension, extra );
				}
			},

			set: function( elem, value, extra ) {
				var matches,
					styles = getStyles( elem ),

					// Only read styles.position if the test has a chance to fail
					// to avoid forcing a reflow.
					scrollboxSizeBuggy = !support.scrollboxSize() &&
						styles.position === "absolute",

					// To avoid forcing a reflow, only fetch boxSizing if we need it (gh-3991)
					boxSizingNeeded = scrollboxSizeBuggy || extra,
					isBorderBox = boxSizingNeeded &&
						jQuery.css( elem, "boxSizing", false, styles ) === "border-box",
					subtract = extra ?
						boxModelAdjustment(
							elem,
							dimension,
							extra,
							isBorderBox,
							styles
						) :
						0;

				// Account for unreliable border-box dimensions by comparing offset* to computed and
				// faking a content-box to get border and padding (gh-3699)
				if ( isBorderBox && scrollboxSizeBuggy ) {
					subtract -= Math.ceil(
						elem[ "offset" + dimension[ 0 ].toUpperCase() + dimension.slice( 1 ) ] -
						parseFloat( styles[ dimension ] ) -
						boxModelAdjustment( elem, dimension, "border", false, styles ) -
						0.5
					);
				}

				// Convert to pixels if value adjustment is needed
				if ( subtract && ( matches = rcssNum.exec( value ) ) &&
					( matches[ 3 ] || "px" ) !== "px" ) {

					elem.style[ dimension ] = value;
					value = jQuery.css( elem, dimension );
				}

				return setPositiveNumber( elem, value, subtract );
			}
		};
	} );

	jQuery.cssHooks.marginLeft = addGetHookIf( support.reliableMarginLeft,
		function( elem, computed ) {
			if ( computed ) {
				return ( parseFloat( curCSS( elem, "marginLeft" ) ) ||
					elem.getBoundingClientRect().left -
						swap( elem, { marginLeft: 0 }, function() {
							return elem.getBoundingClientRect().left;
						} )
				) + "px";
			}
		}
	);

	// These hooks are used by animate to expand properties
	jQuery.each( {
		margin: "",
		padding: "",
		border: "Width"
	}, function( prefix, suffix ) {
		jQuery.cssHooks[ prefix + suffix ] = {
			expand: function( value ) {
				var i = 0,
					expanded = {},

					// Assumes a single number if not a string
					parts = typeof value === "string" ? value.split( " " ) : [ value ];

				for ( ; i < 4; i++ ) {
					expanded[ prefix + cssExpand[ i ] + suffix ] =
						parts[ i ] || parts[ i - 2 ] || parts[ 0 ];
				}

				return expanded;
			}
		};

		if ( prefix !== "margin" ) {
			jQuery.cssHooks[ prefix + suffix ].set = setPositiveNumber;
		}
	} );

	jQuery.fn.extend( {
		css: function( name, value ) {
			return access( this, function( elem, name, value ) {
				var styles, len,
					map = {},
					i = 0;

				if ( Array.isArray( name ) ) {
					styles = getStyles( elem );
					len = name.length;

					for ( ; i < len; i++ ) {
						map[ name[ i ] ] = jQuery.css( elem, name[ i ], false, styles );
					}

					return map;
				}

				return value !== undefined ?
					jQuery.style( elem, name, value ) :
					jQuery.css( elem, name );
			}, name, value, arguments.length > 1 );
		}
	} );


	function Tween( elem, options, prop, end, easing ) {
		return new Tween.prototype.init( elem, options, prop, end, easing );
	}
	jQuery.Tween = Tween;

	Tween.prototype = {
		constructor: Tween,
		init: function( elem, options, prop, end, easing, unit ) {
			this.elem = elem;
			this.prop = prop;
			this.easing = easing || jQuery.easing._default;
			this.options = options;
			this.start = this.now = this.cur();
			this.end = end;
			this.unit = unit || ( jQuery.cssNumber[ prop ] ? "" : "px" );
		},
		cur: function() {
			var hooks = Tween.propHooks[ this.prop ];

			return hooks && hooks.get ?
				hooks.get( this ) :
				Tween.propHooks._default.get( this );
		},
		run: function( percent ) {
			var eased,
				hooks = Tween.propHooks[ this.prop ];

			if ( this.options.duration ) {
				this.pos = eased = jQuery.easing[ this.easing ](
					percent, this.options.duration * percent, 0, 1, this.options.duration
				);
			} else {
				this.pos = eased = percent;
			}
			this.now = ( this.end - this.start ) * eased + this.start;

			if ( this.options.step ) {
				this.options.step.call( this.elem, this.now, this );
			}

			if ( hooks && hooks.set ) {
				hooks.set( this );
			} else {
				Tween.propHooks._default.set( this );
			}
			return this;
		}
	};

	Tween.prototype.init.prototype = Tween.prototype;

	Tween.propHooks = {
		_default: {
			get: function( tween ) {
				var result;

				// Use a property on the element directly when it is not a DOM element,
				// or when there is no matching style property that exists.
				if ( tween.elem.nodeType !== 1 ||
					tween.elem[ tween.prop ] != null && tween.elem.style[ tween.prop ] == null ) {
					return tween.elem[ tween.prop ];
				}

				// Passing an empty string as a 3rd parameter to .css will automatically
				// attempt a parseFloat and fallback to a string if the parse fails.
				// Simple values such as "10px" are parsed to Float;
				// complex values such as "rotate(1rad)" are returned as-is.
				result = jQuery.css( tween.elem, tween.prop, "" );

				// Empty strings, null, undefined and "auto" are converted to 0.
				return !result || result === "auto" ? 0 : result;
			},
			set: function( tween ) {

				// Use step hook for back compat.
				// Use cssHook if its there.
				// Use .style if available and use plain properties where available.
				if ( jQuery.fx.step[ tween.prop ] ) {
					jQuery.fx.step[ tween.prop ]( tween );
				} else if ( tween.elem.nodeType === 1 && (
					jQuery.cssHooks[ tween.prop ] ||
						tween.elem.style[ finalPropName( tween.prop ) ] != null ) ) {
					jQuery.style( tween.elem, tween.prop, tween.now + tween.unit );
				} else {
					tween.elem[ tween.prop ] = tween.now;
				}
			}
		}
	};

	// Support: IE <=9 only
	// Panic based approach to setting things on disconnected nodes
	Tween.propHooks.scrollTop = Tween.propHooks.scrollLeft = {
		set: function( tween ) {
			if ( tween.elem.nodeType && tween.elem.parentNode ) {
				tween.elem[ tween.prop ] = tween.now;
			}
		}
	};

	jQuery.easing = {
		linear: function( p ) {
			return p;
		},
		swing: function( p ) {
			return 0.5 - Math.cos( p * Math.PI ) / 2;
		},
		_default: "swing"
	};

	jQuery.fx = Tween.prototype.init;

	// Back compat <1.8 extension point
	jQuery.fx.step = {};




	var
		fxNow, inProgress,
		rfxtypes = /^(?:toggle|show|hide)$/,
		rrun = /queueHooks$/;

	function schedule() {
		if ( inProgress ) {
			if ( document.hidden === false && window.requestAnimationFrame ) {
				window.requestAnimationFrame( schedule );
			} else {
				window.setTimeout( schedule, jQuery.fx.interval );
			}

			jQuery.fx.tick();
		}
	}

	// Animations created synchronously will run synchronously
	function createFxNow() {
		window.setTimeout( function() {
			fxNow = undefined;
		} );
		return ( fxNow = Date.now() );
	}

	// Generate parameters to create a standard animation
	function genFx( type, includeWidth ) {
		var which,
			i = 0,
			attrs = { height: type };

		// If we include width, step value is 1 to do all cssExpand values,
		// otherwise step value is 2 to skip over Left and Right
		includeWidth = includeWidth ? 1 : 0;
		for ( ; i < 4; i += 2 - includeWidth ) {
			which = cssExpand[ i ];
			attrs[ "margin" + which ] = attrs[ "padding" + which ] = type;
		}

		if ( includeWidth ) {
			attrs.opacity = attrs.width = type;
		}

		return attrs;
	}

	function createTween( value, prop, animation ) {
		var tween,
			collection = ( Animation.tweeners[ prop ] || [] ).concat( Animation.tweeners[ "*" ] ),
			index = 0,
			length = collection.length;
		for ( ; index < length; index++ ) {
			if ( ( tween = collection[ index ].call( animation, prop, value ) ) ) {

				// We're done with this property
				return tween;
			}
		}
	}

	function defaultPrefilter( elem, props, opts ) {
		var prop, value, toggle, hooks, oldfire, propTween, restoreDisplay, display,
			isBox = "width" in props || "height" in props,
			anim = this,
			orig = {},
			style = elem.style,
			hidden = elem.nodeType && isHiddenWithinTree( elem ),
			dataShow = dataPriv.get( elem, "fxshow" );

		// Queue-skipping animations hijack the fx hooks
		if ( !opts.queue ) {
			hooks = jQuery._queueHooks( elem, "fx" );
			if ( hooks.unqueued == null ) {
				hooks.unqueued = 0;
				oldfire = hooks.empty.fire;
				hooks.empty.fire = function() {
					if ( !hooks.unqueued ) {
						oldfire();
					}
				};
			}
			hooks.unqueued++;

			anim.always( function() {

				// Ensure the complete handler is called before this completes
				anim.always( function() {
					hooks.unqueued--;
					if ( !jQuery.queue( elem, "fx" ).length ) {
						hooks.empty.fire();
					}
				} );
			} );
		}

		// Detect show/hide animations
		for ( prop in props ) {
			value = props[ prop ];
			if ( rfxtypes.test( value ) ) {
				delete props[ prop ];
				toggle = toggle || value === "toggle";
				if ( value === ( hidden ? "hide" : "show" ) ) {

					// Pretend to be hidden if this is a "show" and
					// there is still data from a stopped show/hide
					if ( value === "show" && dataShow && dataShow[ prop ] !== undefined ) {
						hidden = true;

					// Ignore all other no-op show/hide data
					} else {
						continue;
					}
				}
				orig[ prop ] = dataShow && dataShow[ prop ] || jQuery.style( elem, prop );
			}
		}

		// Bail out if this is a no-op like .hide().hide()
		propTween = !jQuery.isEmptyObject( props );
		if ( !propTween && jQuery.isEmptyObject( orig ) ) {
			return;
		}

		// Restrict "overflow" and "display" styles during box animations
		if ( isBox && elem.nodeType === 1 ) {

			// Support: IE <=9 - 11, Edge 12 - 15
			// Record all 3 overflow attributes because IE does not infer the shorthand
			// from identically-valued overflowX and overflowY and Edge just mirrors
			// the overflowX value there.
			opts.overflow = [ style.overflow, style.overflowX, style.overflowY ];

			// Identify a display type, preferring old show/hide data over the CSS cascade
			restoreDisplay = dataShow && dataShow.display;
			if ( restoreDisplay == null ) {
				restoreDisplay = dataPriv.get( elem, "display" );
			}
			display = jQuery.css( elem, "display" );
			if ( display === "none" ) {
				if ( restoreDisplay ) {
					display = restoreDisplay;
				} else {

					// Get nonempty value(s) by temporarily forcing visibility
					showHide( [ elem ], true );
					restoreDisplay = elem.style.display || restoreDisplay;
					display = jQuery.css( elem, "display" );
					showHide( [ elem ] );
				}
			}

			// Animate inline elements as inline-block
			if ( display === "inline" || display === "inline-block" && restoreDisplay != null ) {
				if ( jQuery.css( elem, "float" ) === "none" ) {

					// Restore the original display value at the end of pure show/hide animations
					if ( !propTween ) {
						anim.done( function() {
							style.display = restoreDisplay;
						} );
						if ( restoreDisplay == null ) {
							display = style.display;
							restoreDisplay = display === "none" ? "" : display;
						}
					}
					style.display = "inline-block";
				}
			}
		}

		if ( opts.overflow ) {
			style.overflow = "hidden";
			anim.always( function() {
				style.overflow = opts.overflow[ 0 ];
				style.overflowX = opts.overflow[ 1 ];
				style.overflowY = opts.overflow[ 2 ];
			} );
		}

		// Implement show/hide animations
		propTween = false;
		for ( prop in orig ) {

			// General show/hide setup for this element animation
			if ( !propTween ) {
				if ( dataShow ) {
					if ( "hidden" in dataShow ) {
						hidden = dataShow.hidden;
					}
				} else {
					dataShow = dataPriv.access( elem, "fxshow", { display: restoreDisplay } );
				}

				// Store hidden/visible for toggle so `.stop().toggle()` "reverses"
				if ( toggle ) {
					dataShow.hidden = !hidden;
				}

				// Show elements before animating them
				if ( hidden ) {
					showHide( [ elem ], true );
				}

				/* eslint-disable no-loop-func */

				anim.done( function() {

					/* eslint-enable no-loop-func */

					// The final step of a "hide" animation is actually hiding the element
					if ( !hidden ) {
						showHide( [ elem ] );
					}
					dataPriv.remove( elem, "fxshow" );
					for ( prop in orig ) {
						jQuery.style( elem, prop, orig[ prop ] );
					}
				} );
			}

			// Per-property setup
			propTween = createTween( hidden ? dataShow[ prop ] : 0, prop, anim );
			if ( !( prop in dataShow ) ) {
				dataShow[ prop ] = propTween.start;
				if ( hidden ) {
					propTween.end = propTween.start;
					propTween.start = 0;
				}
			}
		}
	}

	function propFilter( props, specialEasing ) {
		var index, name, easing, value, hooks;

		// camelCase, specialEasing and expand cssHook pass
		for ( index in props ) {
			name = camelCase( index );
			easing = specialEasing[ name ];
			value = props[ index ];
			if ( Array.isArray( value ) ) {
				easing = value[ 1 ];
				value = props[ index ] = value[ 0 ];
			}

			if ( index !== name ) {
				props[ name ] = value;
				delete props[ index ];
			}

			hooks = jQuery.cssHooks[ name ];
			if ( hooks && "expand" in hooks ) {
				value = hooks.expand( value );
				delete props[ name ];

				// Not quite $.extend, this won't overwrite existing keys.
				// Reusing 'index' because we have the correct "name"
				for ( index in value ) {
					if ( !( index in props ) ) {
						props[ index ] = value[ index ];
						specialEasing[ index ] = easing;
					}
				}
			} else {
				specialEasing[ name ] = easing;
			}
		}
	}

	function Animation( elem, properties, options ) {
		var result,
			stopped,
			index = 0,
			length = Animation.prefilters.length,
			deferred = jQuery.Deferred().always( function() {

				// Don't match elem in the :animated selector
				delete tick.elem;
			} ),
			tick = function() {
				if ( stopped ) {
					return false;
				}
				var currentTime = fxNow || createFxNow(),
					remaining = Math.max( 0, animation.startTime + animation.duration - currentTime ),

					// Support: Android 2.3 only
					// Archaic crash bug won't allow us to use `1 - ( 0.5 || 0 )` (trac-12497)
					temp = remaining / animation.duration || 0,
					percent = 1 - temp,
					index = 0,
					length = animation.tweens.length;

				for ( ; index < length; index++ ) {
					animation.tweens[ index ].run( percent );
				}

				deferred.notifyWith( elem, [ animation, percent, remaining ] );

				// If there's more to do, yield
				if ( percent < 1 && length ) {
					return remaining;
				}

				// If this was an empty animation, synthesize a final progress notification
				if ( !length ) {
					deferred.notifyWith( elem, [ animation, 1, 0 ] );
				}

				// Resolve the animation and report its conclusion
				deferred.resolveWith( elem, [ animation ] );
				return false;
			},
			animation = deferred.promise( {
				elem: elem,
				props: jQuery.extend( {}, properties ),
				opts: jQuery.extend( true, {
					specialEasing: {},
					easing: jQuery.easing._default
				}, options ),
				originalProperties: properties,
				originalOptions: options,
				startTime: fxNow || createFxNow(),
				duration: options.duration,
				tweens: [],
				createTween: function( prop, end ) {
					var tween = jQuery.Tween( elem, animation.opts, prop, end,
						animation.opts.specialEasing[ prop ] || animation.opts.easing );
					animation.tweens.push( tween );
					return tween;
				},
				stop: function( gotoEnd ) {
					var index = 0,

						// If we are going to the end, we want to run all the tweens
						// otherwise we skip this part
						length = gotoEnd ? animation.tweens.length : 0;
					if ( stopped ) {
						return this;
					}
					stopped = true;
					for ( ; index < length; index++ ) {
						animation.tweens[ index ].run( 1 );
					}

					// Resolve when we played the last frame; otherwise, reject
					if ( gotoEnd ) {
						deferred.notifyWith( elem, [ animation, 1, 0 ] );
						deferred.resolveWith( elem, [ animation, gotoEnd ] );
					} else {
						deferred.rejectWith( elem, [ animation, gotoEnd ] );
					}
					return this;
				}
			} ),
			props = animation.props;

		propFilter( props, animation.opts.specialEasing );

		for ( ; index < length; index++ ) {
			result = Animation.prefilters[ index ].call( animation, elem, props, animation.opts );
			if ( result ) {
				if ( isFunction( result.stop ) ) {
					jQuery._queueHooks( animation.elem, animation.opts.queue ).stop =
						result.stop.bind( result );
				}
				return result;
			}
		}

		jQuery.map( props, createTween, animation );

		if ( isFunction( animation.opts.start ) ) {
			animation.opts.start.call( elem, animation );
		}

		// Attach callbacks from options
		animation
			.progress( animation.opts.progress )
			.done( animation.opts.done, animation.opts.complete )
			.fail( animation.opts.fail )
			.always( animation.opts.always );

		jQuery.fx.timer(
			jQuery.extend( tick, {
				elem: elem,
				anim: animation,
				queue: animation.opts.queue
			} )
		);

		return animation;
	}

	jQuery.Animation = jQuery.extend( Animation, {

		tweeners: {
			"*": [ function( prop, value ) {
				var tween = this.createTween( prop, value );
				adjustCSS( tween.elem, prop, rcssNum.exec( value ), tween );
				return tween;
			} ]
		},

		tweener: function( props, callback ) {
			if ( isFunction( props ) ) {
				callback = props;
				props = [ "*" ];
			} else {
				props = props.match( rnothtmlwhite );
			}

			var prop,
				index = 0,
				length = props.length;

			for ( ; index < length; index++ ) {
				prop = props[ index ];
				Animation.tweeners[ prop ] = Animation.tweeners[ prop ] || [];
				Animation.tweeners[ prop ].unshift( callback );
			}
		},

		prefilters: [ defaultPrefilter ],

		prefilter: function( callback, prepend ) {
			if ( prepend ) {
				Animation.prefilters.unshift( callback );
			} else {
				Animation.prefilters.push( callback );
			}
		}
	} );

	jQuery.speed = function( speed, easing, fn ) {
		var opt = speed && typeof speed === "object" ? jQuery.extend( {}, speed ) : {
			complete: fn || !fn && easing ||
				isFunction( speed ) && speed,
			duration: speed,
			easing: fn && easing || easing && !isFunction( easing ) && easing
		};

		// Go to the end state if fx are off
		if ( jQuery.fx.off ) {
			opt.duration = 0;

		} else {
			if ( typeof opt.duration !== "number" ) {
				if ( opt.duration in jQuery.fx.speeds ) {
					opt.duration = jQuery.fx.speeds[ opt.duration ];

				} else {
					opt.duration = jQuery.fx.speeds._default;
				}
			}
		}

		// Normalize opt.queue - true/undefined/null -> "fx"
		if ( opt.queue == null || opt.queue === true ) {
			opt.queue = "fx";
		}

		// Queueing
		opt.old = opt.complete;

		opt.complete = function() {
			if ( isFunction( opt.old ) ) {
				opt.old.call( this );
			}

			if ( opt.queue ) {
				jQuery.dequeue( this, opt.queue );
			}
		};

		return opt;
	};

	jQuery.fn.extend( {
		fadeTo: function( speed, to, easing, callback ) {

			// Show any hidden elements after setting opacity to 0
			return this.filter( isHiddenWithinTree ).css( "opacity", 0 ).show()

				// Animate to the value specified
				.end().animate( { opacity: to }, speed, easing, callback );
		},
		animate: function( prop, speed, easing, callback ) {
			var empty = jQuery.isEmptyObject( prop ),
				optall = jQuery.speed( speed, easing, callback ),
				doAnimation = function() {

					// Operate on a copy of prop so per-property easing won't be lost
					var anim = Animation( this, jQuery.extend( {}, prop ), optall );

					// Empty animations, or finishing resolves immediately
					if ( empty || dataPriv.get( this, "finish" ) ) {
						anim.stop( true );
					}
				};

			doAnimation.finish = doAnimation;

			return empty || optall.queue === false ?
				this.each( doAnimation ) :
				this.queue( optall.queue, doAnimation );
		},
		stop: function( type, clearQueue, gotoEnd ) {
			var stopQueue = function( hooks ) {
				var stop = hooks.stop;
				delete hooks.stop;
				stop( gotoEnd );
			};

			if ( typeof type !== "string" ) {
				gotoEnd = clearQueue;
				clearQueue = type;
				type = undefined;
			}
			if ( clearQueue ) {
				this.queue( type || "fx", [] );
			}

			return this.each( function() {
				var dequeue = true,
					index = type != null && type + "queueHooks",
					timers = jQuery.timers,
					data = dataPriv.get( this );

				if ( index ) {
					if ( data[ index ] && data[ index ].stop ) {
						stopQueue( data[ index ] );
					}
				} else {
					for ( index in data ) {
						if ( data[ index ] && data[ index ].stop && rrun.test( index ) ) {
							stopQueue( data[ index ] );
						}
					}
				}

				for ( index = timers.length; index--; ) {
					if ( timers[ index ].elem === this &&
						( type == null || timers[ index ].queue === type ) ) {

						timers[ index ].anim.stop( gotoEnd );
						dequeue = false;
						timers.splice( index, 1 );
					}
				}

				// Start the next in the queue if the last step wasn't forced.
				// Timers currently will call their complete callbacks, which
				// will dequeue but only if they were gotoEnd.
				if ( dequeue || !gotoEnd ) {
					jQuery.dequeue( this, type );
				}
			} );
		},
		finish: function( type ) {
			if ( type !== false ) {
				type = type || "fx";
			}
			return this.each( function() {
				var index,
					data = dataPriv.get( this ),
					queue = data[ type + "queue" ],
					hooks = data[ type + "queueHooks" ],
					timers = jQuery.timers,
					length = queue ? queue.length : 0;

				// Enable finishing flag on private data
				data.finish = true;

				// Empty the queue first
				jQuery.queue( this, type, [] );

				if ( hooks && hooks.stop ) {
					hooks.stop.call( this, true );
				}

				// Look for any active animations, and finish them
				for ( index = timers.length; index--; ) {
					if ( timers[ index ].elem === this && timers[ index ].queue === type ) {
						timers[ index ].anim.stop( true );
						timers.splice( index, 1 );
					}
				}

				// Look for any animations in the old queue and finish them
				for ( index = 0; index < length; index++ ) {
					if ( queue[ index ] && queue[ index ].finish ) {
						queue[ index ].finish.call( this );
					}
				}

				// Turn off finishing flag
				delete data.finish;
			} );
		}
	} );

	jQuery.each( [ "toggle", "show", "hide" ], function( _i, name ) {
		var cssFn = jQuery.fn[ name ];
		jQuery.fn[ name ] = function( speed, easing, callback ) {
			return speed == null || typeof speed === "boolean" ?
				cssFn.apply( this, arguments ) :
				this.animate( genFx( name, true ), speed, easing, callback );
		};
	} );

	// Generate shortcuts for custom animations
	jQuery.each( {
		slideDown: genFx( "show" ),
		slideUp: genFx( "hide" ),
		slideToggle: genFx( "toggle" ),
		fadeIn: { opacity: "show" },
		fadeOut: { opacity: "hide" },
		fadeToggle: { opacity: "toggle" }
	}, function( name, props ) {
		jQuery.fn[ name ] = function( speed, easing, callback ) {
			return this.animate( props, speed, easing, callback );
		};
	} );

	jQuery.timers = [];
	jQuery.fx.tick = function() {
		var timer,
			i = 0,
			timers = jQuery.timers;

		fxNow = Date.now();

		for ( ; i < timers.length; i++ ) {
			timer = timers[ i ];

			// Run the timer and safely remove it when done (allowing for external removal)
			if ( !timer() && timers[ i ] === timer ) {
				timers.splice( i--, 1 );
			}
		}

		if ( !timers.length ) {
			jQuery.fx.stop();
		}
		fxNow = undefined;
	};

	jQuery.fx.timer = function( timer ) {
		jQuery.timers.push( timer );
		jQuery.fx.start();
	};

	jQuery.fx.interval = 13;
	jQuery.fx.start = function() {
		if ( inProgress ) {
			return;
		}

		inProgress = true;
		schedule();
	};

	jQuery.fx.stop = function() {
		inProgress = null;
	};

	jQuery.fx.speeds = {
		slow: 600,
		fast: 200,

		// Default speed
		_default: 400
	};


	// Based off of the plugin by Clint Helfers, with permission.
	jQuery.fn.delay = function( time, type ) {
		time = jQuery.fx ? jQuery.fx.speeds[ time ] || time : time;
		type = type || "fx";

		return this.queue( type, function( next, hooks ) {
			var timeout = window.setTimeout( next, time );
			hooks.stop = function() {
				window.clearTimeout( timeout );
			};
		} );
	};


	( function() {
		var input = document.createElement( "input" ),
			select = document.createElement( "select" ),
			opt = select.appendChild( document.createElement( "option" ) );

		input.type = "checkbox";

		// Support: Android <=4.3 only
		// Default value for a checkbox should be "on"
		support.checkOn = input.value !== "";

		// Support: IE <=11 only
		// Must access selectedIndex to make default options select
		support.optSelected = opt.selected;

		// Support: IE <=11 only
		// An input loses its value after becoming a radio
		input = document.createElement( "input" );
		input.value = "t";
		input.type = "radio";
		support.radioValue = input.value === "t";
	} )();


	var boolHook,
		attrHandle = jQuery.expr.attrHandle;

	jQuery.fn.extend( {
		attr: function( name, value ) {
			return access( this, jQuery.attr, name, value, arguments.length > 1 );
		},

		removeAttr: function( name ) {
			return this.each( function() {
				jQuery.removeAttr( this, name );
			} );
		}
	} );

	jQuery.extend( {
		attr: function( elem, name, value ) {
			var ret, hooks,
				nType = elem.nodeType;

			// Don't get/set attributes on text, comment and attribute nodes
			if ( nType === 3 || nType === 8 || nType === 2 ) {
				return;
			}

			// Fallback to prop when attributes are not supported
			if ( typeof elem.getAttribute === "undefined" ) {
				return jQuery.prop( elem, name, value );
			}

			// Attribute hooks are determined by the lowercase version
			// Grab necessary hook if one is defined
			if ( nType !== 1 || !jQuery.isXMLDoc( elem ) ) {
				hooks = jQuery.attrHooks[ name.toLowerCase() ] ||
					( jQuery.expr.match.bool.test( name ) ? boolHook : undefined );
			}

			if ( value !== undefined ) {
				if ( value === null ) {
					jQuery.removeAttr( elem, name );
					return;
				}

				if ( hooks && "set" in hooks &&
					( ret = hooks.set( elem, value, name ) ) !== undefined ) {
					return ret;
				}

				elem.setAttribute( name, value + "" );
				return value;
			}

			if ( hooks && "get" in hooks && ( ret = hooks.get( elem, name ) ) !== null ) {
				return ret;
			}

			ret = jQuery.find.attr( elem, name );

			// Non-existent attributes return null, we normalize to undefined
			return ret == null ? undefined : ret;
		},

		attrHooks: {
			type: {
				set: function( elem, value ) {
					if ( !support.radioValue && value === "radio" &&
						nodeName( elem, "input" ) ) {
						var val = elem.value;
						elem.setAttribute( "type", value );
						if ( val ) {
							elem.value = val;
						}
						return value;
					}
				}
			}
		},

		removeAttr: function( elem, value ) {
			var name,
				i = 0,

				// Attribute names can contain non-HTML whitespace characters
				// https://html.spec.whatwg.org/multipage/syntax.html#attributes-2
				attrNames = value && value.match( rnothtmlwhite );

			if ( attrNames && elem.nodeType === 1 ) {
				while ( ( name = attrNames[ i++ ] ) ) {
					elem.removeAttribute( name );
				}
			}
		}
	} );

	// Hooks for boolean attributes
	boolHook = {
		set: function( elem, value, name ) {
			if ( value === false ) {

				// Remove boolean attributes when set to false
				jQuery.removeAttr( elem, name );
			} else {
				elem.setAttribute( name, name );
			}
			return name;
		}
	};

	jQuery.each( jQuery.expr.match.bool.source.match( /\w+/g ), function( _i, name ) {
		var getter = attrHandle[ name ] || jQuery.find.attr;

		attrHandle[ name ] = function( elem, name, isXML ) {
			var ret, handle,
				lowercaseName = name.toLowerCase();

			if ( !isXML ) {

				// Avoid an infinite loop by temporarily removing this function from the getter
				handle = attrHandle[ lowercaseName ];
				attrHandle[ lowercaseName ] = ret;
				ret = getter( elem, name, isXML ) != null ?
					lowercaseName :
					null;
				attrHandle[ lowercaseName ] = handle;
			}
			return ret;
		};
	} );




	var rfocusable = /^(?:input|select|textarea|button)$/i,
		rclickable = /^(?:a|area)$/i;

	jQuery.fn.extend( {
		prop: function( name, value ) {
			return access( this, jQuery.prop, name, value, arguments.length > 1 );
		},

		removeProp: function( name ) {
			return this.each( function() {
				delete this[ jQuery.propFix[ name ] || name ];
			} );
		}
	} );

	jQuery.extend( {
		prop: function( elem, name, value ) {
			var ret, hooks,
				nType = elem.nodeType;

			// Don't get/set properties on text, comment and attribute nodes
			if ( nType === 3 || nType === 8 || nType === 2 ) {
				return;
			}

			if ( nType !== 1 || !jQuery.isXMLDoc( elem ) ) {

				// Fix name and attach hooks
				name = jQuery.propFix[ name ] || name;
				hooks = jQuery.propHooks[ name ];
			}

			if ( value !== undefined ) {
				if ( hooks && "set" in hooks &&
					( ret = hooks.set( elem, value, name ) ) !== undefined ) {
					return ret;
				}

				return ( elem[ name ] = value );
			}

			if ( hooks && "get" in hooks && ( ret = hooks.get( elem, name ) ) !== null ) {
				return ret;
			}

			return elem[ name ];
		},

		propHooks: {
			tabIndex: {
				get: function( elem ) {

					// Support: IE <=9 - 11 only
					// elem.tabIndex doesn't always return the
					// correct value when it hasn't been explicitly set
					// Use proper attribute retrieval (trac-12072)
					var tabindex = jQuery.find.attr( elem, "tabindex" );

					if ( tabindex ) {
						return parseInt( tabindex, 10 );
					}

					if (
						rfocusable.test( elem.nodeName ) ||
						rclickable.test( elem.nodeName ) &&
						elem.href
					) {
						return 0;
					}

					return -1;
				}
			}
		},

		propFix: {
			"for": "htmlFor",
			"class": "className"
		}
	} );

	// Support: IE <=11 only
	// Accessing the selectedIndex property
	// forces the browser to respect setting selected
	// on the option
	// The getter ensures a default option is selected
	// when in an optgroup
	// eslint rule "no-unused-expressions" is disabled for this code
	// since it considers such accessions noop
	if ( !support.optSelected ) {
		jQuery.propHooks.selected = {
			get: function( elem ) {

				/* eslint no-unused-expressions: "off" */

				var parent = elem.parentNode;
				if ( parent && parent.parentNode ) {
					parent.parentNode.selectedIndex;
				}
				return null;
			},
			set: function( elem ) {

				/* eslint no-unused-expressions: "off" */

				var parent = elem.parentNode;
				if ( parent ) {
					parent.selectedIndex;

					if ( parent.parentNode ) {
						parent.parentNode.selectedIndex;
					}
				}
			}
		};
	}

	jQuery.each( [
		"tabIndex",
		"readOnly",
		"maxLength",
		"cellSpacing",
		"cellPadding",
		"rowSpan",
		"colSpan",
		"useMap",
		"frameBorder",
		"contentEditable"
	], function() {
		jQuery.propFix[ this.toLowerCase() ] = this;
	} );




		// Strip and collapse whitespace according to HTML spec
		// https://infra.spec.whatwg.org/#strip-and-collapse-ascii-whitespace
		function stripAndCollapse( value ) {
			var tokens = value.match( rnothtmlwhite ) || [];
			return tokens.join( " " );
		}


	function getClass( elem ) {
		return elem.getAttribute && elem.getAttribute( "class" ) || "";
	}

	function classesToArray( value ) {
		if ( Array.isArray( value ) ) {
			return value;
		}
		if ( typeof value === "string" ) {
			return value.match( rnothtmlwhite ) || [];
		}
		return [];
	}

	jQuery.fn.extend( {
		addClass: function( value ) {
			var classNames, cur, curValue, className, i, finalValue;

			if ( isFunction( value ) ) {
				return this.each( function( j ) {
					jQuery( this ).addClass( value.call( this, j, getClass( this ) ) );
				} );
			}

			classNames = classesToArray( value );

			if ( classNames.length ) {
				return this.each( function() {
					curValue = getClass( this );
					cur = this.nodeType === 1 && ( " " + stripAndCollapse( curValue ) + " " );

					if ( cur ) {
						for ( i = 0; i < classNames.length; i++ ) {
							className = classNames[ i ];
							if ( cur.indexOf( " " + className + " " ) < 0 ) {
								cur += className + " ";
							}
						}

						// Only assign if different to avoid unneeded rendering.
						finalValue = stripAndCollapse( cur );
						if ( curValue !== finalValue ) {
							this.setAttribute( "class", finalValue );
						}
					}
				} );
			}

			return this;
		},

		removeClass: function( value ) {
			var classNames, cur, curValue, className, i, finalValue;

			if ( isFunction( value ) ) {
				return this.each( function( j ) {
					jQuery( this ).removeClass( value.call( this, j, getClass( this ) ) );
				} );
			}

			if ( !arguments.length ) {
				return this.attr( "class", "" );
			}

			classNames = classesToArray( value );

			if ( classNames.length ) {
				return this.each( function() {
					curValue = getClass( this );

					// This expression is here for better compressibility (see addClass)
					cur = this.nodeType === 1 && ( " " + stripAndCollapse( curValue ) + " " );

					if ( cur ) {
						for ( i = 0; i < classNames.length; i++ ) {
							className = classNames[ i ];

							// Remove *all* instances
							while ( cur.indexOf( " " + className + " " ) > -1 ) {
								cur = cur.replace( " " + className + " ", " " );
							}
						}

						// Only assign if different to avoid unneeded rendering.
						finalValue = stripAndCollapse( cur );
						if ( curValue !== finalValue ) {
							this.setAttribute( "class", finalValue );
						}
					}
				} );
			}

			return this;
		},

		toggleClass: function( value, stateVal ) {
			var classNames, className, i, self,
				type = typeof value,
				isValidValue = type === "string" || Array.isArray( value );

			if ( isFunction( value ) ) {
				return this.each( function( i ) {
					jQuery( this ).toggleClass(
						value.call( this, i, getClass( this ), stateVal ),
						stateVal
					);
				} );
			}

			if ( typeof stateVal === "boolean" && isValidValue ) {
				return stateVal ? this.addClass( value ) : this.removeClass( value );
			}

			classNames = classesToArray( value );

			return this.each( function() {
				if ( isValidValue ) {

					// Toggle individual class names
					self = jQuery( this );

					for ( i = 0; i < classNames.length; i++ ) {
						className = classNames[ i ];

						// Check each className given, space separated list
						if ( self.hasClass( className ) ) {
							self.removeClass( className );
						} else {
							self.addClass( className );
						}
					}

				// Toggle whole class name
				} else if ( value === undefined || type === "boolean" ) {
					className = getClass( this );
					if ( className ) {

						// Store className if set
						dataPriv.set( this, "__className__", className );
					}

					// If the element has a class name or if we're passed `false`,
					// then remove the whole classname (if there was one, the above saved it).
					// Otherwise bring back whatever was previously saved (if anything),
					// falling back to the empty string if nothing was stored.
					if ( this.setAttribute ) {
						this.setAttribute( "class",
							className || value === false ?
								"" :
								dataPriv.get( this, "__className__" ) || ""
						);
					}
				}
			} );
		},

		hasClass: function( selector ) {
			var className, elem,
				i = 0;

			className = " " + selector + " ";
			while ( ( elem = this[ i++ ] ) ) {
				if ( elem.nodeType === 1 &&
					( " " + stripAndCollapse( getClass( elem ) ) + " " ).indexOf( className ) > -1 ) {
					return true;
				}
			}

			return false;
		}
	} );




	var rreturn = /\r/g;

	jQuery.fn.extend( {
		val: function( value ) {
			var hooks, ret, valueIsFunction,
				elem = this[ 0 ];

			if ( !arguments.length ) {
				if ( elem ) {
					hooks = jQuery.valHooks[ elem.type ] ||
						jQuery.valHooks[ elem.nodeName.toLowerCase() ];

					if ( hooks &&
						"get" in hooks &&
						( ret = hooks.get( elem, "value" ) ) !== undefined
					) {
						return ret;
					}

					ret = elem.value;

					// Handle most common string cases
					if ( typeof ret === "string" ) {
						return ret.replace( rreturn, "" );
					}

					// Handle cases where value is null/undef or number
					return ret == null ? "" : ret;
				}

				return;
			}

			valueIsFunction = isFunction( value );

			return this.each( function( i ) {
				var val;

				if ( this.nodeType !== 1 ) {
					return;
				}

				if ( valueIsFunction ) {
					val = value.call( this, i, jQuery( this ).val() );
				} else {
					val = value;
				}

				// Treat null/undefined as ""; convert numbers to string
				if ( val == null ) {
					val = "";

				} else if ( typeof val === "number" ) {
					val += "";

				} else if ( Array.isArray( val ) ) {
					val = jQuery.map( val, function( value ) {
						return value == null ? "" : value + "";
					} );
				}

				hooks = jQuery.valHooks[ this.type ] || jQuery.valHooks[ this.nodeName.toLowerCase() ];

				// If set returns undefined, fall back to normal setting
				if ( !hooks || !( "set" in hooks ) || hooks.set( this, val, "value" ) === undefined ) {
					this.value = val;
				}
			} );
		}
	} );

	jQuery.extend( {
		valHooks: {
			option: {
				get: function( elem ) {

					var val = jQuery.find.attr( elem, "value" );
					return val != null ?
						val :

						// Support: IE <=10 - 11 only
						// option.text throws exceptions (trac-14686, trac-14858)
						// Strip and collapse whitespace
						// https://html.spec.whatwg.org/#strip-and-collapse-whitespace
						stripAndCollapse( jQuery.text( elem ) );
				}
			},
			select: {
				get: function( elem ) {
					var value, option, i,
						options = elem.options,
						index = elem.selectedIndex,
						one = elem.type === "select-one",
						values = one ? null : [],
						max = one ? index + 1 : options.length;

					if ( index < 0 ) {
						i = max;

					} else {
						i = one ? index : 0;
					}

					// Loop through all the selected options
					for ( ; i < max; i++ ) {
						option = options[ i ];

						// Support: IE <=9 only
						// IE8-9 doesn't update selected after form reset (trac-2551)
						if ( ( option.selected || i === index ) &&

								// Don't return options that are disabled or in a disabled optgroup
								!option.disabled &&
								( !option.parentNode.disabled ||
									!nodeName( option.parentNode, "optgroup" ) ) ) {

							// Get the specific value for the option
							value = jQuery( option ).val();

							// We don't need an array for one selects
							if ( one ) {
								return value;
							}

							// Multi-Selects return an array
							values.push( value );
						}
					}

					return values;
				},

				set: function( elem, value ) {
					var optionSet, option,
						options = elem.options,
						values = jQuery.makeArray( value ),
						i = options.length;

					while ( i-- ) {
						option = options[ i ];

						/* eslint-disable no-cond-assign */

						if ( option.selected =
							jQuery.inArray( jQuery.valHooks.option.get( option ), values ) > -1
						) {
							optionSet = true;
						}

						/* eslint-enable no-cond-assign */
					}

					// Force browsers to behave consistently when non-matching value is set
					if ( !optionSet ) {
						elem.selectedIndex = -1;
					}
					return values;
				}
			}
		}
	} );

	// Radios and checkboxes getter/setter
	jQuery.each( [ "radio", "checkbox" ], function() {
		jQuery.valHooks[ this ] = {
			set: function( elem, value ) {
				if ( Array.isArray( value ) ) {
					return ( elem.checked = jQuery.inArray( jQuery( elem ).val(), value ) > -1 );
				}
			}
		};
		if ( !support.checkOn ) {
			jQuery.valHooks[ this ].get = function( elem ) {
				return elem.getAttribute( "value" ) === null ? "on" : elem.value;
			};
		}
	} );




	// Return jQuery for attributes-only inclusion
	var location = window.location;

	var nonce = { guid: Date.now() };

	var rquery = ( /\?/ );



	// Cross-browser xml parsing
	jQuery.parseXML = function( data ) {
		var xml, parserErrorElem;
		if ( !data || typeof data !== "string" ) {
			return null;
		}

		// Support: IE 9 - 11 only
		// IE throws on parseFromString with invalid input.
		try {
			xml = ( new window.DOMParser() ).parseFromString( data, "text/xml" );
		} catch ( e ) {}

		parserErrorElem = xml && xml.getElementsByTagName( "parsererror" )[ 0 ];
		if ( !xml || parserErrorElem ) {
			jQuery.error( "Invalid XML: " + (
				parserErrorElem ?
					jQuery.map( parserErrorElem.childNodes, function( el ) {
						return el.textContent;
					} ).join( "\n" ) :
					data
			) );
		}
		return xml;
	};


	var rfocusMorph = /^(?:focusinfocus|focusoutblur)$/,
		stopPropagationCallback = function( e ) {
			e.stopPropagation();
		};

	jQuery.extend( jQuery.event, {

		trigger: function( event, data, elem, onlyHandlers ) {

			var i, cur, tmp, bubbleType, ontype, handle, special, lastElement,
				eventPath = [ elem || document ],
				type = hasOwn.call( event, "type" ) ? event.type : event,
				namespaces = hasOwn.call( event, "namespace" ) ? event.namespace.split( "." ) : [];

			cur = lastElement = tmp = elem = elem || document;

			// Don't do events on text and comment nodes
			if ( elem.nodeType === 3 || elem.nodeType === 8 ) {
				return;
			}

			// focus/blur morphs to focusin/out; ensure we're not firing them right now
			if ( rfocusMorph.test( type + jQuery.event.triggered ) ) {
				return;
			}

			if ( type.indexOf( "." ) > -1 ) {

				// Namespaced trigger; create a regexp to match event type in handle()
				namespaces = type.split( "." );
				type = namespaces.shift();
				namespaces.sort();
			}
			ontype = type.indexOf( ":" ) < 0 && "on" + type;

			// Caller can pass in a jQuery.Event object, Object, or just an event type string
			event = event[ jQuery.expando ] ?
				event :
				new jQuery.Event( type, typeof event === "object" && event );

			// Trigger bitmask: & 1 for native handlers; & 2 for jQuery (always true)
			event.isTrigger = onlyHandlers ? 2 : 3;
			event.namespace = namespaces.join( "." );
			event.rnamespace = event.namespace ?
				new RegExp( "(^|\\.)" + namespaces.join( "\\.(?:.*\\.|)" ) + "(\\.|$)" ) :
				null;

			// Clean up the event in case it is being reused
			event.result = undefined;
			if ( !event.target ) {
				event.target = elem;
			}

			// Clone any incoming data and prepend the event, creating the handler arg list
			data = data == null ?
				[ event ] :
				jQuery.makeArray( data, [ event ] );

			// Allow special events to draw outside the lines
			special = jQuery.event.special[ type ] || {};
			if ( !onlyHandlers && special.trigger && special.trigger.apply( elem, data ) === false ) {
				return;
			}

			// Determine event propagation path in advance, per W3C events spec (trac-9951)
			// Bubble up to document, then to window; watch for a global ownerDocument var (trac-9724)
			if ( !onlyHandlers && !special.noBubble && !isWindow( elem ) ) {

				bubbleType = special.delegateType || type;
				if ( !rfocusMorph.test( bubbleType + type ) ) {
					cur = cur.parentNode;
				}
				for ( ; cur; cur = cur.parentNode ) {
					eventPath.push( cur );
					tmp = cur;
				}

				// Only add window if we got to document (e.g., not plain obj or detached DOM)
				if ( tmp === ( elem.ownerDocument || document ) ) {
					eventPath.push( tmp.defaultView || tmp.parentWindow || window );
				}
			}

			// Fire handlers on the event path
			i = 0;
			while ( ( cur = eventPath[ i++ ] ) && !event.isPropagationStopped() ) {
				lastElement = cur;
				event.type = i > 1 ?
					bubbleType :
					special.bindType || type;

				// jQuery handler
				handle = ( dataPriv.get( cur, "events" ) || Object.create( null ) )[ event.type ] &&
					dataPriv.get( cur, "handle" );
				if ( handle ) {
					handle.apply( cur, data );
				}

				// Native handler
				handle = ontype && cur[ ontype ];
				if ( handle && handle.apply && acceptData( cur ) ) {
					event.result = handle.apply( cur, data );
					if ( event.result === false ) {
						event.preventDefault();
					}
				}
			}
			event.type = type;

			// If nobody prevented the default action, do it now
			if ( !onlyHandlers && !event.isDefaultPrevented() ) {

				if ( ( !special._default ||
					special._default.apply( eventPath.pop(), data ) === false ) &&
					acceptData( elem ) ) {

					// Call a native DOM method on the target with the same name as the event.
					// Don't do default actions on window, that's where global variables be (trac-6170)
					if ( ontype && isFunction( elem[ type ] ) && !isWindow( elem ) ) {

						// Don't re-trigger an onFOO event when we call its FOO() method
						tmp = elem[ ontype ];

						if ( tmp ) {
							elem[ ontype ] = null;
						}

						// Prevent re-triggering of the same event, since we already bubbled it above
						jQuery.event.triggered = type;

						if ( event.isPropagationStopped() ) {
							lastElement.addEventListener( type, stopPropagationCallback );
						}

						elem[ type ]();

						if ( event.isPropagationStopped() ) {
							lastElement.removeEventListener( type, stopPropagationCallback );
						}

						jQuery.event.triggered = undefined;

						if ( tmp ) {
							elem[ ontype ] = tmp;
						}
					}
				}
			}

			return event.result;
		},

		// Piggyback on a donor event to simulate a different one
		// Used only for `focus(in | out)` events
		simulate: function( type, elem, event ) {
			var e = jQuery.extend(
				new jQuery.Event(),
				event,
				{
					type: type,
					isSimulated: true
				}
			);

			jQuery.event.trigger( e, null, elem );
		}

	} );

	jQuery.fn.extend( {

		trigger: function( type, data ) {
			return this.each( function() {
				jQuery.event.trigger( type, data, this );
			} );
		},
		triggerHandler: function( type, data ) {
			var elem = this[ 0 ];
			if ( elem ) {
				return jQuery.event.trigger( type, data, elem, true );
			}
		}
	} );


	var
		rbracket = /\[\]$/,
		rCRLF = /\r?\n/g,
		rsubmitterTypes = /^(?:submit|button|image|reset|file)$/i,
		rsubmittable = /^(?:input|select|textarea|keygen)/i;

	function buildParams( prefix, obj, traditional, add ) {
		var name;

		if ( Array.isArray( obj ) ) {

			// Serialize array item.
			jQuery.each( obj, function( i, v ) {
				if ( traditional || rbracket.test( prefix ) ) {

					// Treat each array item as a scalar.
					add( prefix, v );

				} else {

					// Item is non-scalar (array or object), encode its numeric index.
					buildParams(
						prefix + "[" + ( typeof v === "object" && v != null ? i : "" ) + "]",
						v,
						traditional,
						add
					);
				}
			} );

		} else if ( !traditional && toType( obj ) === "object" ) {

			// Serialize object item.
			for ( name in obj ) {
				buildParams( prefix + "[" + name + "]", obj[ name ], traditional, add );
			}

		} else {

			// Serialize scalar item.
			add( prefix, obj );
		}
	}

	// Serialize an array of form elements or a set of
	// key/values into a query string
	jQuery.param = function( a, traditional ) {
		var prefix,
			s = [],
			add = function( key, valueOrFunction ) {

				// If value is a function, invoke it and use its return value
				var value = isFunction( valueOrFunction ) ?
					valueOrFunction() :
					valueOrFunction;

				s[ s.length ] = encodeURIComponent( key ) + "=" +
					encodeURIComponent( value == null ? "" : value );
			};

		if ( a == null ) {
			return "";
		}

		// If an array was passed in, assume that it is an array of form elements.
		if ( Array.isArray( a ) || ( a.jquery && !jQuery.isPlainObject( a ) ) ) {

			// Serialize the form elements
			jQuery.each( a, function() {
				add( this.name, this.value );
			} );

		} else {

			// If traditional, encode the "old" way (the way 1.3.2 or older
			// did it), otherwise encode params recursively.
			for ( prefix in a ) {
				buildParams( prefix, a[ prefix ], traditional, add );
			}
		}

		// Return the resulting serialization
		return s.join( "&" );
	};

	jQuery.fn.extend( {
		serialize: function() {
			return jQuery.param( this.serializeArray() );
		},
		serializeArray: function() {
			return this.map( function() {

				// Can add propHook for "elements" to filter or add form elements
				var elements = jQuery.prop( this, "elements" );
				return elements ? jQuery.makeArray( elements ) : this;
			} ).filter( function() {
				var type = this.type;

				// Use .is( ":disabled" ) so that fieldset[disabled] works
				return this.name && !jQuery( this ).is( ":disabled" ) &&
					rsubmittable.test( this.nodeName ) && !rsubmitterTypes.test( type ) &&
					( this.checked || !rcheckableType.test( type ) );
			} ).map( function( _i, elem ) {
				var val = jQuery( this ).val();

				if ( val == null ) {
					return null;
				}

				if ( Array.isArray( val ) ) {
					return jQuery.map( val, function( val ) {
						return { name: elem.name, value: val.replace( rCRLF, "\r\n" ) };
					} );
				}

				return { name: elem.name, value: val.replace( rCRLF, "\r\n" ) };
			} ).get();
		}
	} );


	var
		r20 = /%20/g,
		rhash = /#.*$/,
		rantiCache = /([?&])_=[^&]*/,
		rheaders = /^(.*?):[ \t]*([^\r\n]*)$/mg,

		// trac-7653, trac-8125, trac-8152: local protocol detection
		rlocalProtocol = /^(?:about|app|app-storage|.+-extension|file|res|widget):$/,
		rnoContent = /^(?:GET|HEAD)$/,
		rprotocol = /^\/\//,

		/* Prefilters
		 * 1) They are useful to introduce custom dataTypes (see ajax/jsonp.js for an example)
		 * 2) These are called:
		 *    - BEFORE asking for a transport
		 *    - AFTER param serialization (s.data is a string if s.processData is true)
		 * 3) key is the dataType
		 * 4) the catchall symbol "*" can be used
		 * 5) execution will start with transport dataType and THEN continue down to "*" if needed
		 */
		prefilters = {},

		/* Transports bindings
		 * 1) key is the dataType
		 * 2) the catchall symbol "*" can be used
		 * 3) selection will start with transport dataType and THEN go to "*" if needed
		 */
		transports = {},

		// Avoid comment-prolog char sequence (trac-10098); must appease lint and evade compression
		allTypes = "*/".concat( "*" ),

		// Anchor tag for parsing the document origin
		originAnchor = document.createElement( "a" );

	originAnchor.href = location.href;

	// Base "constructor" for jQuery.ajaxPrefilter and jQuery.ajaxTransport
	function addToPrefiltersOrTransports( structure ) {

		// dataTypeExpression is optional and defaults to "*"
		return function( dataTypeExpression, func ) {

			if ( typeof dataTypeExpression !== "string" ) {
				func = dataTypeExpression;
				dataTypeExpression = "*";
			}

			var dataType,
				i = 0,
				dataTypes = dataTypeExpression.toLowerCase().match( rnothtmlwhite ) || [];

			if ( isFunction( func ) ) {

				// For each dataType in the dataTypeExpression
				while ( ( dataType = dataTypes[ i++ ] ) ) {

					// Prepend if requested
					if ( dataType[ 0 ] === "+" ) {
						dataType = dataType.slice( 1 ) || "*";
						( structure[ dataType ] = structure[ dataType ] || [] ).unshift( func );

					// Otherwise append
					} else {
						( structure[ dataType ] = structure[ dataType ] || [] ).push( func );
					}
				}
			}
		};
	}

	// Base inspection function for prefilters and transports
	function inspectPrefiltersOrTransports( structure, options, originalOptions, jqXHR ) {

		var inspected = {},
			seekingTransport = ( structure === transports );

		function inspect( dataType ) {
			var selected;
			inspected[ dataType ] = true;
			jQuery.each( structure[ dataType ] || [], function( _, prefilterOrFactory ) {
				var dataTypeOrTransport = prefilterOrFactory( options, originalOptions, jqXHR );
				if ( typeof dataTypeOrTransport === "string" &&
					!seekingTransport && !inspected[ dataTypeOrTransport ] ) {

					options.dataTypes.unshift( dataTypeOrTransport );
					inspect( dataTypeOrTransport );
					return false;
				} else if ( seekingTransport ) {
					return !( selected = dataTypeOrTransport );
				}
			} );
			return selected;
		}

		return inspect( options.dataTypes[ 0 ] ) || !inspected[ "*" ] && inspect( "*" );
	}

	// A special extend for ajax options
	// that takes "flat" options (not to be deep extended)
	// Fixes trac-9887
	function ajaxExtend( target, src ) {
		var key, deep,
			flatOptions = jQuery.ajaxSettings.flatOptions || {};

		for ( key in src ) {
			if ( src[ key ] !== undefined ) {
				( flatOptions[ key ] ? target : ( deep || ( deep = {} ) ) )[ key ] = src[ key ];
			}
		}
		if ( deep ) {
			jQuery.extend( true, target, deep );
		}

		return target;
	}

	/* Handles responses to an ajax request:
	 * - finds the right dataType (mediates between content-type and expected dataType)
	 * - returns the corresponding response
	 */
	function ajaxHandleResponses( s, jqXHR, responses ) {

		var ct, type, finalDataType, firstDataType,
			contents = s.contents,
			dataTypes = s.dataTypes;

		// Remove auto dataType and get content-type in the process
		while ( dataTypes[ 0 ] === "*" ) {
			dataTypes.shift();
			if ( ct === undefined ) {
				ct = s.mimeType || jqXHR.getResponseHeader( "Content-Type" );
			}
		}

		// Check if we're dealing with a known content-type
		if ( ct ) {
			for ( type in contents ) {
				if ( contents[ type ] && contents[ type ].test( ct ) ) {
					dataTypes.unshift( type );
					break;
				}
			}
		}

		// Check to see if we have a response for the expected dataType
		if ( dataTypes[ 0 ] in responses ) {
			finalDataType = dataTypes[ 0 ];
		} else {

			// Try convertible dataTypes
			for ( type in responses ) {
				if ( !dataTypes[ 0 ] || s.converters[ type + " " + dataTypes[ 0 ] ] ) {
					finalDataType = type;
					break;
				}
				if ( !firstDataType ) {
					firstDataType = type;
				}
			}

			// Or just use first one
			finalDataType = finalDataType || firstDataType;
		}

		// If we found a dataType
		// We add the dataType to the list if needed
		// and return the corresponding response
		if ( finalDataType ) {
			if ( finalDataType !== dataTypes[ 0 ] ) {
				dataTypes.unshift( finalDataType );
			}
			return responses[ finalDataType ];
		}
	}

	/* Chain conversions given the request and the original response
	 * Also sets the responseXXX fields on the jqXHR instance
	 */
	function ajaxConvert( s, response, jqXHR, isSuccess ) {
		var conv2, current, conv, tmp, prev,
			converters = {},

			// Work with a copy of dataTypes in case we need to modify it for conversion
			dataTypes = s.dataTypes.slice();

		// Create converters map with lowercased keys
		if ( dataTypes[ 1 ] ) {
			for ( conv in s.converters ) {
				converters[ conv.toLowerCase() ] = s.converters[ conv ];
			}
		}

		current = dataTypes.shift();

		// Convert to each sequential dataType
		while ( current ) {

			if ( s.responseFields[ current ] ) {
				jqXHR[ s.responseFields[ current ] ] = response;
			}

			// Apply the dataFilter if provided
			if ( !prev && isSuccess && s.dataFilter ) {
				response = s.dataFilter( response, s.dataType );
			}

			prev = current;
			current = dataTypes.shift();

			if ( current ) {

				// There's only work to do if current dataType is non-auto
				if ( current === "*" ) {

					current = prev;

				// Convert response if prev dataType is non-auto and differs from current
				} else if ( prev !== "*" && prev !== current ) {

					// Seek a direct converter
					conv = converters[ prev + " " + current ] || converters[ "* " + current ];

					// If none found, seek a pair
					if ( !conv ) {
						for ( conv2 in converters ) {

							// If conv2 outputs current
							tmp = conv2.split( " " );
							if ( tmp[ 1 ] === current ) {

								// If prev can be converted to accepted input
								conv = converters[ prev + " " + tmp[ 0 ] ] ||
									converters[ "* " + tmp[ 0 ] ];
								if ( conv ) {

									// Condense equivalence converters
									if ( conv === true ) {
										conv = converters[ conv2 ];

									// Otherwise, insert the intermediate dataType
									} else if ( converters[ conv2 ] !== true ) {
										current = tmp[ 0 ];
										dataTypes.unshift( tmp[ 1 ] );
									}
									break;
								}
							}
						}
					}

					// Apply converter (if not an equivalence)
					if ( conv !== true ) {

						// Unless errors are allowed to bubble, catch and return them
						if ( conv && s.throws ) {
							response = conv( response );
						} else {
							try {
								response = conv( response );
							} catch ( e ) {
								return {
									state: "parsererror",
									error: conv ? e : "No conversion from " + prev + " to " + current
								};
							}
						}
					}
				}
			}
		}

		return { state: "success", data: response };
	}

	jQuery.extend( {

		// Counter for holding the number of active queries
		active: 0,

		// Last-Modified header cache for next request
		lastModified: {},
		etag: {},

		ajaxSettings: {
			url: location.href,
			type: "GET",
			isLocal: rlocalProtocol.test( location.protocol ),
			global: true,
			processData: true,
			async: true,
			contentType: "application/x-www-form-urlencoded; charset=UTF-8",

			/*
			timeout: 0,
			data: null,
			dataType: null,
			username: null,
			password: null,
			cache: null,
			throws: false,
			traditional: false,
			headers: {},
			*/

			accepts: {
				"*": allTypes,
				text: "text/plain",
				html: "text/html",
				xml: "application/xml, text/xml",
				json: "application/json, text/javascript"
			},

			contents: {
				xml: /\bxml\b/,
				html: /\bhtml/,
				json: /\bjson\b/
			},

			responseFields: {
				xml: "responseXML",
				text: "responseText",
				json: "responseJSON"
			},

			// Data converters
			// Keys separate source (or catchall "*") and destination types with a single space
			converters: {

				// Convert anything to text
				"* text": String,

				// Text to html (true = no transformation)
				"text html": true,

				// Evaluate text as a json expression
				"text json": JSON.parse,

				// Parse text as xml
				"text xml": jQuery.parseXML
			},

			// For options that shouldn't be deep extended:
			// you can add your own custom options here if
			// and when you create one that shouldn't be
			// deep extended (see ajaxExtend)
			flatOptions: {
				url: true,
				context: true
			}
		},

		// Creates a full fledged settings object into target
		// with both ajaxSettings and settings fields.
		// If target is omitted, writes into ajaxSettings.
		ajaxSetup: function( target, settings ) {
			return settings ?

				// Building a settings object
				ajaxExtend( ajaxExtend( target, jQuery.ajaxSettings ), settings ) :

				// Extending ajaxSettings
				ajaxExtend( jQuery.ajaxSettings, target );
		},

		ajaxPrefilter: addToPrefiltersOrTransports( prefilters ),
		ajaxTransport: addToPrefiltersOrTransports( transports ),

		// Main method
		ajax: function( url, options ) {

			// If url is an object, simulate pre-1.5 signature
			if ( typeof url === "object" ) {
				options = url;
				url = undefined;
			}

			// Force options to be an object
			options = options || {};

			var transport,

				// URL without anti-cache param
				cacheURL,

				// Response headers
				responseHeadersString,
				responseHeaders,

				// timeout handle
				timeoutTimer,

				// Url cleanup var
				urlAnchor,

				// Request state (becomes false upon send and true upon completion)
				completed,

				// To know if global events are to be dispatched
				fireGlobals,

				// Loop variable
				i,

				// uncached part of the url
				uncached,

				// Create the final options object
				s = jQuery.ajaxSetup( {}, options ),

				// Callbacks context
				callbackContext = s.context || s,

				// Context for global events is callbackContext if it is a DOM node or jQuery collection
				globalEventContext = s.context &&
					( callbackContext.nodeType || callbackContext.jquery ) ?
					jQuery( callbackContext ) :
					jQuery.event,

				// Deferreds
				deferred = jQuery.Deferred(),
				completeDeferred = jQuery.Callbacks( "once memory" ),

				// Status-dependent callbacks
				statusCode = s.statusCode || {},

				// Headers (they are sent all at once)
				requestHeaders = {},
				requestHeadersNames = {},

				// Default abort message
				strAbort = "canceled",

				// Fake xhr
				jqXHR = {
					readyState: 0,

					// Builds headers hashtable if needed
					getResponseHeader: function( key ) {
						var match;
						if ( completed ) {
							if ( !responseHeaders ) {
								responseHeaders = {};
								while ( ( match = rheaders.exec( responseHeadersString ) ) ) {
									responseHeaders[ match[ 1 ].toLowerCase() + " " ] =
										( responseHeaders[ match[ 1 ].toLowerCase() + " " ] || [] )
											.concat( match[ 2 ] );
								}
							}
							match = responseHeaders[ key.toLowerCase() + " " ];
						}
						return match == null ? null : match.join( ", " );
					},

					// Raw string
					getAllResponseHeaders: function() {
						return completed ? responseHeadersString : null;
					},

					// Caches the header
					setRequestHeader: function( name, value ) {
						if ( completed == null ) {
							name = requestHeadersNames[ name.toLowerCase() ] =
								requestHeadersNames[ name.toLowerCase() ] || name;
							requestHeaders[ name ] = value;
						}
						return this;
					},

					// Overrides response content-type header
					overrideMimeType: function( type ) {
						if ( completed == null ) {
							s.mimeType = type;
						}
						return this;
					},

					// Status-dependent callbacks
					statusCode: function( map ) {
						var code;
						if ( map ) {
							if ( completed ) {

								// Execute the appropriate callbacks
								jqXHR.always( map[ jqXHR.status ] );
							} else {

								// Lazy-add the new callbacks in a way that preserves old ones
								for ( code in map ) {
									statusCode[ code ] = [ statusCode[ code ], map[ code ] ];
								}
							}
						}
						return this;
					},

					// Cancel the request
					abort: function( statusText ) {
						var finalText = statusText || strAbort;
						if ( transport ) {
							transport.abort( finalText );
						}
						done( 0, finalText );
						return this;
					}
				};

			// Attach deferreds
			deferred.promise( jqXHR );

			// Add protocol if not provided (prefilters might expect it)
			// Handle falsy url in the settings object (trac-10093: consistency with old signature)
			// We also use the url parameter if available
			s.url = ( ( url || s.url || location.href ) + "" )
				.replace( rprotocol, location.protocol + "//" );

			// Alias method option to type as per ticket trac-12004
			s.type = options.method || options.type || s.method || s.type;

			// Extract dataTypes list
			s.dataTypes = ( s.dataType || "*" ).toLowerCase().match( rnothtmlwhite ) || [ "" ];

			// A cross-domain request is in order when the origin doesn't match the current origin.
			if ( s.crossDomain == null ) {
				urlAnchor = document.createElement( "a" );

				// Support: IE <=8 - 11, Edge 12 - 15
				// IE throws exception on accessing the href property if url is malformed,
				// e.g. http://example.com:80x/
				try {
					urlAnchor.href = s.url;

					// Support: IE <=8 - 11 only
					// Anchor's host property isn't correctly set when s.url is relative
					urlAnchor.href = urlAnchor.href;
					s.crossDomain = originAnchor.protocol + "//" + originAnchor.host !==
						urlAnchor.protocol + "//" + urlAnchor.host;
				} catch ( e ) {

					// If there is an error parsing the URL, assume it is crossDomain,
					// it can be rejected by the transport if it is invalid
					s.crossDomain = true;
				}
			}

			// Convert data if not already a string
			if ( s.data && s.processData && typeof s.data !== "string" ) {
				s.data = jQuery.param( s.data, s.traditional );
			}

			// Apply prefilters
			inspectPrefiltersOrTransports( prefilters, s, options, jqXHR );

			// If request was aborted inside a prefilter, stop there
			if ( completed ) {
				return jqXHR;
			}

			// We can fire global events as of now if asked to
			// Don't fire events if jQuery.event is undefined in an AMD-usage scenario (trac-15118)
			fireGlobals = jQuery.event && s.global;

			// Watch for a new set of requests
			if ( fireGlobals && jQuery.active++ === 0 ) {
				jQuery.event.trigger( "ajaxStart" );
			}

			// Uppercase the type
			s.type = s.type.toUpperCase();

			// Determine if request has content
			s.hasContent = !rnoContent.test( s.type );

			// Save the URL in case we're toying with the If-Modified-Since
			// and/or If-None-Match header later on
			// Remove hash to simplify url manipulation
			cacheURL = s.url.replace( rhash, "" );

			// More options handling for requests with no content
			if ( !s.hasContent ) {

				// Remember the hash so we can put it back
				uncached = s.url.slice( cacheURL.length );

				// If data is available and should be processed, append data to url
				if ( s.data && ( s.processData || typeof s.data === "string" ) ) {
					cacheURL += ( rquery.test( cacheURL ) ? "&" : "?" ) + s.data;

					// trac-9682: remove data so that it's not used in an eventual retry
					delete s.data;
				}

				// Add or update anti-cache param if needed
				if ( s.cache === false ) {
					cacheURL = cacheURL.replace( rantiCache, "$1" );
					uncached = ( rquery.test( cacheURL ) ? "&" : "?" ) + "_=" + ( nonce.guid++ ) +
						uncached;
				}

				// Put hash and anti-cache on the URL that will be requested (gh-1732)
				s.url = cacheURL + uncached;

			// Change '%20' to '+' if this is encoded form body content (gh-2658)
			} else if ( s.data && s.processData &&
				( s.contentType || "" ).indexOf( "application/x-www-form-urlencoded" ) === 0 ) {
				s.data = s.data.replace( r20, "+" );
			}

			// Set the If-Modified-Since and/or If-None-Match header, if in ifModified mode.
			if ( s.ifModified ) {
				if ( jQuery.lastModified[ cacheURL ] ) {
					jqXHR.setRequestHeader( "If-Modified-Since", jQuery.lastModified[ cacheURL ] );
				}
				if ( jQuery.etag[ cacheURL ] ) {
					jqXHR.setRequestHeader( "If-None-Match", jQuery.etag[ cacheURL ] );
				}
			}

			// Set the correct header, if data is being sent
			if ( s.data && s.hasContent && s.contentType !== false || options.contentType ) {
				jqXHR.setRequestHeader( "Content-Type", s.contentType );
			}

			// Set the Accepts header for the server, depending on the dataType
			jqXHR.setRequestHeader(
				"Accept",
				s.dataTypes[ 0 ] && s.accepts[ s.dataTypes[ 0 ] ] ?
					s.accepts[ s.dataTypes[ 0 ] ] +
						( s.dataTypes[ 0 ] !== "*" ? ", " + allTypes + "; q=0.01" : "" ) :
					s.accepts[ "*" ]
			);

			// Check for headers option
			for ( i in s.headers ) {
				jqXHR.setRequestHeader( i, s.headers[ i ] );
			}

			// Allow custom headers/mimetypes and early abort
			if ( s.beforeSend &&
				( s.beforeSend.call( callbackContext, jqXHR, s ) === false || completed ) ) {

				// Abort if not done already and return
				return jqXHR.abort();
			}

			// Aborting is no longer a cancellation
			strAbort = "abort";

			// Install callbacks on deferreds
			completeDeferred.add( s.complete );
			jqXHR.done( s.success );
			jqXHR.fail( s.error );

			// Get transport
			transport = inspectPrefiltersOrTransports( transports, s, options, jqXHR );

			// If no transport, we auto-abort
			if ( !transport ) {
				done( -1, "No Transport" );
			} else {
				jqXHR.readyState = 1;

				// Send global event
				if ( fireGlobals ) {
					globalEventContext.trigger( "ajaxSend", [ jqXHR, s ] );
				}

				// If request was aborted inside ajaxSend, stop there
				if ( completed ) {
					return jqXHR;
				}

				// Timeout
				if ( s.async && s.timeout > 0 ) {
					timeoutTimer = window.setTimeout( function() {
						jqXHR.abort( "timeout" );
					}, s.timeout );
				}

				try {
					completed = false;
					transport.send( requestHeaders, done );
				} catch ( e ) {

					// Rethrow post-completion exceptions
					if ( completed ) {
						throw e;
					}

					// Propagate others as results
					done( -1, e );
				}
			}

			// Callback for when everything is done
			function done( status, nativeStatusText, responses, headers ) {
				var isSuccess, success, error, response, modified,
					statusText = nativeStatusText;

				// Ignore repeat invocations
				if ( completed ) {
					return;
				}

				completed = true;

				// Clear timeout if it exists
				if ( timeoutTimer ) {
					window.clearTimeout( timeoutTimer );
				}

				// Dereference transport for early garbage collection
				// (no matter how long the jqXHR object will be used)
				transport = undefined;

				// Cache response headers
				responseHeadersString = headers || "";

				// Set readyState
				jqXHR.readyState = status > 0 ? 4 : 0;

				// Determine if successful
				isSuccess = status >= 200 && status < 300 || status === 304;

				// Get response data
				if ( responses ) {
					response = ajaxHandleResponses( s, jqXHR, responses );
				}

				// Use a noop converter for missing script but not if jsonp
				if ( !isSuccess &&
					jQuery.inArray( "script", s.dataTypes ) > -1 &&
					jQuery.inArray( "json", s.dataTypes ) < 0 ) {
					s.converters[ "text script" ] = function() {};
				}

				// Convert no matter what (that way responseXXX fields are always set)
				response = ajaxConvert( s, response, jqXHR, isSuccess );

				// If successful, handle type chaining
				if ( isSuccess ) {

					// Set the If-Modified-Since and/or If-None-Match header, if in ifModified mode.
					if ( s.ifModified ) {
						modified = jqXHR.getResponseHeader( "Last-Modified" );
						if ( modified ) {
							jQuery.lastModified[ cacheURL ] = modified;
						}
						modified = jqXHR.getResponseHeader( "etag" );
						if ( modified ) {
							jQuery.etag[ cacheURL ] = modified;
						}
					}

					// if no content
					if ( status === 204 || s.type === "HEAD" ) {
						statusText = "nocontent";

					// if not modified
					} else if ( status === 304 ) {
						statusText = "notmodified";

					// If we have data, let's convert it
					} else {
						statusText = response.state;
						success = response.data;
						error = response.error;
						isSuccess = !error;
					}
				} else {

					// Extract error from statusText and normalize for non-aborts
					error = statusText;
					if ( status || !statusText ) {
						statusText = "error";
						if ( status < 0 ) {
							status = 0;
						}
					}
				}

				// Set data for the fake xhr object
				jqXHR.status = status;
				jqXHR.statusText = ( nativeStatusText || statusText ) + "";

				// Success/Error
				if ( isSuccess ) {
					deferred.resolveWith( callbackContext, [ success, statusText, jqXHR ] );
				} else {
					deferred.rejectWith( callbackContext, [ jqXHR, statusText, error ] );
				}

				// Status-dependent callbacks
				jqXHR.statusCode( statusCode );
				statusCode = undefined;

				if ( fireGlobals ) {
					globalEventContext.trigger( isSuccess ? "ajaxSuccess" : "ajaxError",
						[ jqXHR, s, isSuccess ? success : error ] );
				}

				// Complete
				completeDeferred.fireWith( callbackContext, [ jqXHR, statusText ] );

				if ( fireGlobals ) {
					globalEventContext.trigger( "ajaxComplete", [ jqXHR, s ] );

					// Handle the global AJAX counter
					if ( !( --jQuery.active ) ) {
						jQuery.event.trigger( "ajaxStop" );
					}
				}
			}

			return jqXHR;
		},

		getJSON: function( url, data, callback ) {
			return jQuery.get( url, data, callback, "json" );
		},

		getScript: function( url, callback ) {
			return jQuery.get( url, undefined, callback, "script" );
		}
	} );

	jQuery.each( [ "get", "post" ], function( _i, method ) {
		jQuery[ method ] = function( url, data, callback, type ) {

			// Shift arguments if data argument was omitted
			if ( isFunction( data ) ) {
				type = type || callback;
				callback = data;
				data = undefined;
			}

			// The url can be an options object (which then must have .url)
			return jQuery.ajax( jQuery.extend( {
				url: url,
				type: method,
				dataType: type,
				data: data,
				success: callback
			}, jQuery.isPlainObject( url ) && url ) );
		};
	} );

	jQuery.ajaxPrefilter( function( s ) {
		var i;
		for ( i in s.headers ) {
			if ( i.toLowerCase() === "content-type" ) {
				s.contentType = s.headers[ i ] || "";
			}
		}
	} );


	jQuery._evalUrl = function( url, options, doc ) {
		return jQuery.ajax( {
			url: url,

			// Make this explicit, since user can override this through ajaxSetup (trac-11264)
			type: "GET",
			dataType: "script",
			cache: true,
			async: false,
			global: false,

			// Only evaluate the response if it is successful (gh-4126)
			// dataFilter is not invoked for failure responses, so using it instead
			// of the default converter is kludgy but it works.
			converters: {
				"text script": function() {}
			},
			dataFilter: function( response ) {
				jQuery.globalEval( response, options, doc );
			}
		} );
	};


	jQuery.fn.extend( {
		wrapAll: function( html ) {
			var wrap;

			if ( this[ 0 ] ) {
				if ( isFunction( html ) ) {
					html = html.call( this[ 0 ] );
				}

				// The elements to wrap the target around
				wrap = jQuery( html, this[ 0 ].ownerDocument ).eq( 0 ).clone( true );

				if ( this[ 0 ].parentNode ) {
					wrap.insertBefore( this[ 0 ] );
				}

				wrap.map( function() {
					var elem = this;

					while ( elem.firstElementChild ) {
						elem = elem.firstElementChild;
					}

					return elem;
				} ).append( this );
			}

			return this;
		},

		wrapInner: function( html ) {
			if ( isFunction( html ) ) {
				return this.each( function( i ) {
					jQuery( this ).wrapInner( html.call( this, i ) );
				} );
			}

			return this.each( function() {
				var self = jQuery( this ),
					contents = self.contents();

				if ( contents.length ) {
					contents.wrapAll( html );

				} else {
					self.append( html );
				}
			} );
		},

		wrap: function( html ) {
			var htmlIsFunction = isFunction( html );

			return this.each( function( i ) {
				jQuery( this ).wrapAll( htmlIsFunction ? html.call( this, i ) : html );
			} );
		},

		unwrap: function( selector ) {
			this.parent( selector ).not( "body" ).each( function() {
				jQuery( this ).replaceWith( this.childNodes );
			} );
			return this;
		}
	} );


	jQuery.expr.pseudos.hidden = function( elem ) {
		return !jQuery.expr.pseudos.visible( elem );
	};
	jQuery.expr.pseudos.visible = function( elem ) {
		return !!( elem.offsetWidth || elem.offsetHeight || elem.getClientRects().length );
	};




	jQuery.ajaxSettings.xhr = function() {
		try {
			return new window.XMLHttpRequest();
		} catch ( e ) {}
	};

	var xhrSuccessStatus = {

			// File protocol always yields status code 0, assume 200
			0: 200,

			// Support: IE <=9 only
			// trac-1450: sometimes IE returns 1223 when it should be 204
			1223: 204
		},
		xhrSupported = jQuery.ajaxSettings.xhr();

	support.cors = !!xhrSupported && ( "withCredentials" in xhrSupported );
	support.ajax = xhrSupported = !!xhrSupported;

	jQuery.ajaxTransport( function( options ) {
		var callback, errorCallback;

		// Cross domain only allowed if supported through XMLHttpRequest
		if ( support.cors || xhrSupported && !options.crossDomain ) {
			return {
				send: function( headers, complete ) {
					var i,
						xhr = options.xhr();

					xhr.open(
						options.type,
						options.url,
						options.async,
						options.username,
						options.password
					);

					// Apply custom fields if provided
					if ( options.xhrFields ) {
						for ( i in options.xhrFields ) {
							xhr[ i ] = options.xhrFields[ i ];
						}
					}

					// Override mime type if needed
					if ( options.mimeType && xhr.overrideMimeType ) {
						xhr.overrideMimeType( options.mimeType );
					}

					// X-Requested-With header
					// For cross-domain requests, seeing as conditions for a preflight are
					// akin to a jigsaw puzzle, we simply never set it to be sure.
					// (it can always be set on a per-request basis or even using ajaxSetup)
					// For same-domain requests, won't change header if already provided.
					if ( !options.crossDomain && !headers[ "X-Requested-With" ] ) {
						headers[ "X-Requested-With" ] = "XMLHttpRequest";
					}

					// Set headers
					for ( i in headers ) {
						xhr.setRequestHeader( i, headers[ i ] );
					}

					// Callback
					callback = function( type ) {
						return function() {
							if ( callback ) {
								callback = errorCallback = xhr.onload =
									xhr.onerror = xhr.onabort = xhr.ontimeout =
										xhr.onreadystatechange = null;

								if ( type === "abort" ) {
									xhr.abort();
								} else if ( type === "error" ) {

									// Support: IE <=9 only
									// On a manual native abort, IE9 throws
									// errors on any property access that is not readyState
									if ( typeof xhr.status !== "number" ) {
										complete( 0, "error" );
									} else {
										complete(

											// File: protocol always yields status 0; see trac-8605, trac-14207
											xhr.status,
											xhr.statusText
										);
									}
								} else {
									complete(
										xhrSuccessStatus[ xhr.status ] || xhr.status,
										xhr.statusText,

										// Support: IE <=9 only
										// IE9 has no XHR2 but throws on binary (trac-11426)
										// For XHR2 non-text, let the caller handle it (gh-2498)
										( xhr.responseType || "text" ) !== "text"  ||
										typeof xhr.responseText !== "string" ?
											{ binary: xhr.response } :
											{ text: xhr.responseText },
										xhr.getAllResponseHeaders()
									);
								}
							}
						};
					};

					// Listen to events
					xhr.onload = callback();
					errorCallback = xhr.onerror = xhr.ontimeout = callback( "error" );

					// Support: IE 9 only
					// Use onreadystatechange to replace onabort
					// to handle uncaught aborts
					if ( xhr.onabort !== undefined ) {
						xhr.onabort = errorCallback;
					} else {
						xhr.onreadystatechange = function() {

							// Check readyState before timeout as it changes
							if ( xhr.readyState === 4 ) {

								// Allow onerror to be called first,
								// but that will not handle a native abort
								// Also, save errorCallback to a variable
								// as xhr.onerror cannot be accessed
								window.setTimeout( function() {
									if ( callback ) {
										errorCallback();
									}
								} );
							}
						};
					}

					// Create the abort callback
					callback = callback( "abort" );

					try {

						// Do send the request (this may raise an exception)
						xhr.send( options.hasContent && options.data || null );
					} catch ( e ) {

						// trac-14683: Only rethrow if this hasn't been notified as an error yet
						if ( callback ) {
							throw e;
						}
					}
				},

				abort: function() {
					if ( callback ) {
						callback();
					}
				}
			};
		}
	} );




	// Prevent auto-execution of scripts when no explicit dataType was provided (See gh-2432)
	jQuery.ajaxPrefilter( function( s ) {
		if ( s.crossDomain ) {
			s.contents.script = false;
		}
	} );

	// Install script dataType
	jQuery.ajaxSetup( {
		accepts: {
			script: "text/javascript, application/javascript, " +
				"application/ecmascript, application/x-ecmascript"
		},
		contents: {
			script: /\b(?:java|ecma)script\b/
		},
		converters: {
			"text script": function( text ) {
				jQuery.globalEval( text );
				return text;
			}
		}
	} );

	// Handle cache's special case and crossDomain
	jQuery.ajaxPrefilter( "script", function( s ) {
		if ( s.cache === undefined ) {
			s.cache = false;
		}
		if ( s.crossDomain ) {
			s.type = "GET";
		}
	} );

	// Bind script tag hack transport
	jQuery.ajaxTransport( "script", function( s ) {

		// This transport only deals with cross domain or forced-by-attrs requests
		if ( s.crossDomain || s.scriptAttrs ) {
			var script, callback;
			return {
				send: function( _, complete ) {
					script = jQuery( "<script>" )
						.attr( s.scriptAttrs || {} )
						.prop( { charset: s.scriptCharset, src: s.url } )
						.on( "load error", callback = function( evt ) {
							script.remove();
							callback = null;
							if ( evt ) {
								complete( evt.type === "error" ? 404 : 200, evt.type );
							}
						} );

					// Use native DOM manipulation to avoid our domManip AJAX trickery
					document.head.appendChild( script[ 0 ] );
				},
				abort: function() {
					if ( callback ) {
						callback();
					}
				}
			};
		}
	} );




	var oldCallbacks = [],
		rjsonp = /(=)\?(?=&|$)|\?\?/;

	// Default jsonp settings
	jQuery.ajaxSetup( {
		jsonp: "callback",
		jsonpCallback: function() {
			var callback = oldCallbacks.pop() || ( jQuery.expando + "_" + ( nonce.guid++ ) );
			this[ callback ] = true;
			return callback;
		}
	} );

	// Detect, normalize options and install callbacks for jsonp requests
	jQuery.ajaxPrefilter( "json jsonp", function( s, originalSettings, jqXHR ) {

		var callbackName, overwritten, responseContainer,
			jsonProp = s.jsonp !== false && ( rjsonp.test( s.url ) ?
				"url" :
				typeof s.data === "string" &&
					( s.contentType || "" )
						.indexOf( "application/x-www-form-urlencoded" ) === 0 &&
					rjsonp.test( s.data ) && "data"
			);

		// Handle iff the expected data type is "jsonp" or we have a parameter to set
		if ( jsonProp || s.dataTypes[ 0 ] === "jsonp" ) {

			// Get callback name, remembering preexisting value associated with it
			callbackName = s.jsonpCallback = isFunction( s.jsonpCallback ) ?
				s.jsonpCallback() :
				s.jsonpCallback;

			// Insert callback into url or form data
			if ( jsonProp ) {
				s[ jsonProp ] = s[ jsonProp ].replace( rjsonp, "$1" + callbackName );
			} else if ( s.jsonp !== false ) {
				s.url += ( rquery.test( s.url ) ? "&" : "?" ) + s.jsonp + "=" + callbackName;
			}

			// Use data converter to retrieve json after script execution
			s.converters[ "script json" ] = function() {
				if ( !responseContainer ) {
					jQuery.error( callbackName + " was not called" );
				}
				return responseContainer[ 0 ];
			};

			// Force json dataType
			s.dataTypes[ 0 ] = "json";

			// Install callback
			overwritten = window[ callbackName ];
			window[ callbackName ] = function() {
				responseContainer = arguments;
			};

			// Clean-up function (fires after converters)
			jqXHR.always( function() {

				// If previous value didn't exist - remove it
				if ( overwritten === undefined ) {
					jQuery( window ).removeProp( callbackName );

				// Otherwise restore preexisting value
				} else {
					window[ callbackName ] = overwritten;
				}

				// Save back as free
				if ( s[ callbackName ] ) {

					// Make sure that re-using the options doesn't screw things around
					s.jsonpCallback = originalSettings.jsonpCallback;

					// Save the callback name for future use
					oldCallbacks.push( callbackName );
				}

				// Call if it was a function and we have a response
				if ( responseContainer && isFunction( overwritten ) ) {
					overwritten( responseContainer[ 0 ] );
				}

				responseContainer = overwritten = undefined;
			} );

			// Delegate to script
			return "script";
		}
	} );




	// Support: Safari 8 only
	// In Safari 8 documents created via document.implementation.createHTMLDocument
	// collapse sibling forms: the second one becomes a child of the first one.
	// Because of that, this security measure has to be disabled in Safari 8.
	// https://bugs.webkit.org/show_bug.cgi?id=137337
	support.createHTMLDocument = ( function() {
		var body = document.implementation.createHTMLDocument( "" ).body;
		body.innerHTML = "<form></form><form></form>";
		return body.childNodes.length === 2;
	} )();


	// Argument "data" should be string of html
	// context (optional): If specified, the fragment will be created in this context,
	// defaults to document
	// keepScripts (optional): If true, will include scripts passed in the html string
	jQuery.parseHTML = function( data, context, keepScripts ) {
		if ( typeof data !== "string" ) {
			return [];
		}
		if ( typeof context === "boolean" ) {
			keepScripts = context;
			context = false;
		}

		var base, parsed, scripts;

		if ( !context ) {

			// Stop scripts or inline event handlers from being executed immediately
			// by using document.implementation
			if ( support.createHTMLDocument ) {
				context = document.implementation.createHTMLDocument( "" );

				// Set the base href for the created document
				// so any parsed elements with URLs
				// are based on the document's URL (gh-2965)
				base = context.createElement( "base" );
				base.href = document.location.href;
				context.head.appendChild( base );
			} else {
				context = document;
			}
		}

		parsed = rsingleTag.exec( data );
		scripts = !keepScripts && [];

		// Single tag
		if ( parsed ) {
			return [ context.createElement( parsed[ 1 ] ) ];
		}

		parsed = buildFragment( [ data ], context, scripts );

		if ( scripts && scripts.length ) {
			jQuery( scripts ).remove();
		}

		return jQuery.merge( [], parsed.childNodes );
	};


	/**
	 * Load a url into a page
	 */
	jQuery.fn.load = function( url, params, callback ) {
		var selector, type, response,
			self = this,
			off = url.indexOf( " " );

		if ( off > -1 ) {
			selector = stripAndCollapse( url.slice( off ) );
			url = url.slice( 0, off );
		}

		// If it's a function
		if ( isFunction( params ) ) {

			// We assume that it's the callback
			callback = params;
			params = undefined;

		// Otherwise, build a param string
		} else if ( params && typeof params === "object" ) {
			type = "POST";
		}

		// If we have elements to modify, make the request
		if ( self.length > 0 ) {
			jQuery.ajax( {
				url: url,

				// If "type" variable is undefined, then "GET" method will be used.
				// Make value of this field explicit since
				// user can override it through ajaxSetup method
				type: type || "GET",
				dataType: "html",
				data: params
			} ).done( function( responseText ) {

				// Save response for use in complete callback
				response = arguments;

				self.html( selector ?

					// If a selector was specified, locate the right elements in a dummy div
					// Exclude scripts to avoid IE 'Permission Denied' errors
					jQuery( "<div>" ).append( jQuery.parseHTML( responseText ) ).find( selector ) :

					// Otherwise use the full result
					responseText );

			// If the request succeeds, this function gets "data", "status", "jqXHR"
			// but they are ignored because response was set above.
			// If it fails, this function gets "jqXHR", "status", "error"
			} ).always( callback && function( jqXHR, status ) {
				self.each( function() {
					callback.apply( this, response || [ jqXHR.responseText, status, jqXHR ] );
				} );
			} );
		}

		return this;
	};




	jQuery.expr.pseudos.animated = function( elem ) {
		return jQuery.grep( jQuery.timers, function( fn ) {
			return elem === fn.elem;
		} ).length;
	};




	jQuery.offset = {
		setOffset: function( elem, options, i ) {
			var curPosition, curLeft, curCSSTop, curTop, curOffset, curCSSLeft, calculatePosition,
				position = jQuery.css( elem, "position" ),
				curElem = jQuery( elem ),
				props = {};

			// Set position first, in-case top/left are set even on static elem
			if ( position === "static" ) {
				elem.style.position = "relative";
			}

			curOffset = curElem.offset();
			curCSSTop = jQuery.css( elem, "top" );
			curCSSLeft = jQuery.css( elem, "left" );
			calculatePosition = ( position === "absolute" || position === "fixed" ) &&
				( curCSSTop + curCSSLeft ).indexOf( "auto" ) > -1;

			// Need to be able to calculate position if either
			// top or left is auto and position is either absolute or fixed
			if ( calculatePosition ) {
				curPosition = curElem.position();
				curTop = curPosition.top;
				curLeft = curPosition.left;

			} else {
				curTop = parseFloat( curCSSTop ) || 0;
				curLeft = parseFloat( curCSSLeft ) || 0;
			}

			if ( isFunction( options ) ) {

				// Use jQuery.extend here to allow modification of coordinates argument (gh-1848)
				options = options.call( elem, i, jQuery.extend( {}, curOffset ) );
			}

			if ( options.top != null ) {
				props.top = ( options.top - curOffset.top ) + curTop;
			}
			if ( options.left != null ) {
				props.left = ( options.left - curOffset.left ) + curLeft;
			}

			if ( "using" in options ) {
				options.using.call( elem, props );

			} else {
				curElem.css( props );
			}
		}
	};

	jQuery.fn.extend( {

		// offset() relates an element's border box to the document origin
		offset: function( options ) {

			// Preserve chaining for setter
			if ( arguments.length ) {
				return options === undefined ?
					this :
					this.each( function( i ) {
						jQuery.offset.setOffset( this, options, i );
					} );
			}

			var rect, win,
				elem = this[ 0 ];

			if ( !elem ) {
				return;
			}

			// Return zeros for disconnected and hidden (display: none) elements (gh-2310)
			// Support: IE <=11 only
			// Running getBoundingClientRect on a
			// disconnected node in IE throws an error
			if ( !elem.getClientRects().length ) {
				return { top: 0, left: 0 };
			}

			// Get document-relative position by adding viewport scroll to viewport-relative gBCR
			rect = elem.getBoundingClientRect();
			win = elem.ownerDocument.defaultView;
			return {
				top: rect.top + win.pageYOffset,
				left: rect.left + win.pageXOffset
			};
		},

		// position() relates an element's margin box to its offset parent's padding box
		// This corresponds to the behavior of CSS absolute positioning
		position: function() {
			if ( !this[ 0 ] ) {
				return;
			}

			var offsetParent, offset, doc,
				elem = this[ 0 ],
				parentOffset = { top: 0, left: 0 };

			// position:fixed elements are offset from the viewport, which itself always has zero offset
			if ( jQuery.css( elem, "position" ) === "fixed" ) {

				// Assume position:fixed implies availability of getBoundingClientRect
				offset = elem.getBoundingClientRect();

			} else {
				offset = this.offset();

				// Account for the *real* offset parent, which can be the document or its root element
				// when a statically positioned element is identified
				doc = elem.ownerDocument;
				offsetParent = elem.offsetParent || doc.documentElement;
				while ( offsetParent &&
					( offsetParent === doc.body || offsetParent === doc.documentElement ) &&
					jQuery.css( offsetParent, "position" ) === "static" ) {

					offsetParent = offsetParent.parentNode;
				}
				if ( offsetParent && offsetParent !== elem && offsetParent.nodeType === 1 ) {

					// Incorporate borders into its offset, since they are outside its content origin
					parentOffset = jQuery( offsetParent ).offset();
					parentOffset.top += jQuery.css( offsetParent, "borderTopWidth", true );
					parentOffset.left += jQuery.css( offsetParent, "borderLeftWidth", true );
				}
			}

			// Subtract parent offsets and element margins
			return {
				top: offset.top - parentOffset.top - jQuery.css( elem, "marginTop", true ),
				left: offset.left - parentOffset.left - jQuery.css( elem, "marginLeft", true )
			};
		},

		// This method will return documentElement in the following cases:
		// 1) For the element inside the iframe without offsetParent, this method will return
		//    documentElement of the parent window
		// 2) For the hidden or detached element
		// 3) For body or html element, i.e. in case of the html node - it will return itself
		//
		// but those exceptions were never presented as a real life use-cases
		// and might be considered as more preferable results.
		//
		// This logic, however, is not guaranteed and can change at any point in the future
		offsetParent: function() {
			return this.map( function() {
				var offsetParent = this.offsetParent;

				while ( offsetParent && jQuery.css( offsetParent, "position" ) === "static" ) {
					offsetParent = offsetParent.offsetParent;
				}

				return offsetParent || documentElement;
			} );
		}
	} );

	// Create scrollLeft and scrollTop methods
	jQuery.each( { scrollLeft: "pageXOffset", scrollTop: "pageYOffset" }, function( method, prop ) {
		var top = "pageYOffset" === prop;

		jQuery.fn[ method ] = function( val ) {
			return access( this, function( elem, method, val ) {

				// Coalesce documents and windows
				var win;
				if ( isWindow( elem ) ) {
					win = elem;
				} else if ( elem.nodeType === 9 ) {
					win = elem.defaultView;
				}

				if ( val === undefined ) {
					return win ? win[ prop ] : elem[ method ];
				}

				if ( win ) {
					win.scrollTo(
						!top ? val : win.pageXOffset,
						top ? val : win.pageYOffset
					);

				} else {
					elem[ method ] = val;
				}
			}, method, val, arguments.length );
		};
	} );

	// Support: Safari <=7 - 9.1, Chrome <=37 - 49
	// Add the top/left cssHooks using jQuery.fn.position
	// Webkit bug: https://bugs.webkit.org/show_bug.cgi?id=29084
	// Blink bug: https://bugs.chromium.org/p/chromium/issues/detail?id=589347
	// getComputedStyle returns percent when specified for top/left/bottom/right;
	// rather than make the css module depend on the offset module, just check for it here
	jQuery.each( [ "top", "left" ], function( _i, prop ) {
		jQuery.cssHooks[ prop ] = addGetHookIf( support.pixelPosition,
			function( elem, computed ) {
				if ( computed ) {
					computed = curCSS( elem, prop );

					// If curCSS returns percentage, fallback to offset
					return rnumnonpx.test( computed ) ?
						jQuery( elem ).position()[ prop ] + "px" :
						computed;
				}
			}
		);
	} );


	// Create innerHeight, innerWidth, height, width, outerHeight and outerWidth methods
	jQuery.each( { Height: "height", Width: "width" }, function( name, type ) {
		jQuery.each( {
			padding: "inner" + name,
			content: type,
			"": "outer" + name
		}, function( defaultExtra, funcName ) {

			// Margin is only for outerHeight, outerWidth
			jQuery.fn[ funcName ] = function( margin, value ) {
				var chainable = arguments.length && ( defaultExtra || typeof margin !== "boolean" ),
					extra = defaultExtra || ( margin === true || value === true ? "margin" : "border" );

				return access( this, function( elem, type, value ) {
					var doc;

					if ( isWindow( elem ) ) {

						// $( window ).outerWidth/Height return w/h including scrollbars (gh-1729)
						return funcName.indexOf( "outer" ) === 0 ?
							elem[ "inner" + name ] :
							elem.document.documentElement[ "client" + name ];
					}

					// Get document width or height
					if ( elem.nodeType === 9 ) {
						doc = elem.documentElement;

						// Either scroll[Width/Height] or offset[Width/Height] or client[Width/Height],
						// whichever is greatest
						return Math.max(
							elem.body[ "scroll" + name ], doc[ "scroll" + name ],
							elem.body[ "offset" + name ], doc[ "offset" + name ],
							doc[ "client" + name ]
						);
					}

					return value === undefined ?

						// Get width or height on the element, requesting but not forcing parseFloat
						jQuery.css( elem, type, extra ) :

						// Set width or height on the element
						jQuery.style( elem, type, value, extra );
				}, type, chainable ? margin : undefined, chainable );
			};
		} );
	} );


	jQuery.each( [
		"ajaxStart",
		"ajaxStop",
		"ajaxComplete",
		"ajaxError",
		"ajaxSuccess",
		"ajaxSend"
	], function( _i, type ) {
		jQuery.fn[ type ] = function( fn ) {
			return this.on( type, fn );
		};
	} );




	jQuery.fn.extend( {

		bind: function( types, data, fn ) {
			return this.on( types, null, data, fn );
		},
		unbind: function( types, fn ) {
			return this.off( types, null, fn );
		},

		delegate: function( selector, types, data, fn ) {
			return this.on( types, selector, data, fn );
		},
		undelegate: function( selector, types, fn ) {

			// ( namespace ) or ( selector, types [, fn] )
			return arguments.length === 1 ?
				this.off( selector, "**" ) :
				this.off( types, selector || "**", fn );
		},

		hover: function( fnOver, fnOut ) {
			return this
				.on( "mouseenter", fnOver )
				.on( "mouseleave", fnOut || fnOver );
		}
	} );

	jQuery.each(
		( "blur focus focusin focusout resize scroll click dblclick " +
		"mousedown mouseup mousemove mouseover mouseout mouseenter mouseleave " +
		"change select submit keydown keypress keyup contextmenu" ).split( " " ),
		function( _i, name ) {

			// Handle event binding
			jQuery.fn[ name ] = function( data, fn ) {
				return arguments.length > 0 ?
					this.on( name, null, data, fn ) :
					this.trigger( name );
			};
		}
	);




	// Support: Android <=4.0 only
	// Make sure we trim BOM and NBSP
	// Require that the "whitespace run" starts from a non-whitespace
	// to avoid O(N^2) behavior when the engine would try matching "\s+$" at each space position.
	var rtrim = /^[\s\uFEFF\xA0]+|([^\s\uFEFF\xA0])[\s\uFEFF\xA0]+$/g;

	// Bind a function to a context, optionally partially applying any
	// arguments.
	// jQuery.proxy is deprecated to promote standards (specifically Function#bind)
	// However, it is not slated for removal any time soon
	jQuery.proxy = function( fn, context ) {
		var tmp, args, proxy;

		if ( typeof context === "string" ) {
			tmp = fn[ context ];
			context = fn;
			fn = tmp;
		}

		// Quick check to determine if target is callable, in the spec
		// this throws a TypeError, but we will just return undefined.
		if ( !isFunction( fn ) ) {
			return undefined;
		}

		// Simulated bind
		args = slice.call( arguments, 2 );
		proxy = function() {
			return fn.apply( context || this, args.concat( slice.call( arguments ) ) );
		};

		// Set the guid of unique handler to the same of original handler, so it can be removed
		proxy.guid = fn.guid = fn.guid || jQuery.guid++;

		return proxy;
	};

	jQuery.holdReady = function( hold ) {
		if ( hold ) {
			jQuery.readyWait++;
		} else {
			jQuery.ready( true );
		}
	};
	jQuery.isArray = Array.isArray;
	jQuery.parseJSON = JSON.parse;
	jQuery.nodeName = nodeName;
	jQuery.isFunction = isFunction;
	jQuery.isWindow = isWindow;
	jQuery.camelCase = camelCase;
	jQuery.type = toType;

	jQuery.now = Date.now;

	jQuery.isNumeric = function( obj ) {

		// As of jQuery 3.0, isNumeric is limited to
		// strings and numbers (primitives or objects)
		// that can be coerced to finite numbers (gh-2662)
		var type = jQuery.type( obj );
		return ( type === "number" || type === "string" ) &&

			// parseFloat NaNs numeric-cast false positives ("")
			// ...but misinterprets leading-number strings, particularly hex literals ("0x...")
			// subtraction forces infinities to NaN
			!isNaN( obj - parseFloat( obj ) );
	};

	jQuery.trim = function( text ) {
		return text == null ?
			"" :
			( text + "" ).replace( rtrim, "$1" );
	};



	// Register as a named AMD module, since jQuery can be concatenated with other
	// files that may use define, but not via a proper concatenation script that
	// understands anonymous AMD modules. A named AMD is safest and most robust
	// way to register. Lowercase jquery is used because AMD module names are
	// derived from file names, and jQuery is normally delivered in a lowercase
	// file name. Do this after creating the global so that if an AMD module wants
	// to call noConflict to hide this version of jQuery, it will work.

	// Note that for maximum portability, libraries that are not jQuery should
	// declare themselves as anonymous modules, and avoid setting a global if an
	// AMD loader is present. jQuery is a special case. For more information, see
	// https://github.com/jrburke/requirejs/wiki/Updating-existing-libraries#wiki-anon

	if ( true ) {
		!(__WEBPACK_AMD_DEFINE_ARRAY__ = [], __WEBPACK_AMD_DEFINE_RESULT__ = function() {
			return jQuery;
		}.apply(exports, __WEBPACK_AMD_DEFINE_ARRAY__), __WEBPACK_AMD_DEFINE_RESULT__ !== undefined && (module.exports = __WEBPACK_AMD_DEFINE_RESULT__));
	}




	var

		// Map over jQuery in case of overwrite
		_jQuery = window.jQuery,

		// Map over the $ in case of overwrite
		_$ = window.$;

	jQuery.noConflict = function( deep ) {
		if ( window.$ === jQuery ) {
			window.$ = _$;
		}

		if ( deep && window.jQuery === jQuery ) {
			window.jQuery = _jQuery;
		}

		return jQuery;
	};

	// Expose jQuery and $ identifiers, even in AMD
	// (trac-7102#comment:10, https://github.com/jquery/jquery/pull/557)
	// and CommonJS for browser emulators (trac-13566)
	if ( typeof noGlobal === "undefined" ) {
		window.jQuery = window.$ = jQuery;
	}




	return jQuery;
	} );


/***/ }),
/* 4 */
/***/ (function(module, exports) {

	module.exports = __WEBPACK_EXTERNAL_MODULE_4__;

/***/ }),
/* 5 */
/***/ (function(module, exports) {

	module.exports = __WEBPACK_EXTERNAL_MODULE_5__;

/***/ }),
/* 6 */
/***/ (function(module, exports, __webpack_require__) {

	/* WEBPACK VAR INJECTION */(function(global) {(function (global, factory) {
	   true ? module.exports = factory() :
	  typeof define === 'function' && define.amd ? define('underscore', factory) :
	  (global = typeof globalThis !== 'undefined' ? globalThis : global || self, (function () {
	    var current = global._;
	    var exports = global._ = factory();
	    exports.noConflict = function () { global._ = current; return exports; };
	  }()));
	}(this, (function () {
	  //     Underscore.js 1.13.6
	  //     https://underscorejs.org
	  //     (c) 2009-2022 Jeremy Ashkenas, Julian Gonggrijp, and DocumentCloud and Investigative Reporters & Editors
	  //     Underscore may be freely distributed under the MIT license.

	  // Current version.
	  var VERSION = '1.13.6';

	  // Establish the root object, `window` (`self`) in the browser, `global`
	  // on the server, or `this` in some virtual machines. We use `self`
	  // instead of `window` for `WebWorker` support.
	  var root = (typeof self == 'object' && self.self === self && self) ||
	            (typeof global == 'object' && global.global === global && global) ||
	            Function('return this')() ||
	            {};

	  // Save bytes in the minified (but not gzipped) version:
	  var ArrayProto = Array.prototype, ObjProto = Object.prototype;
	  var SymbolProto = typeof Symbol !== 'undefined' ? Symbol.prototype : null;

	  // Create quick reference variables for speed access to core prototypes.
	  var push = ArrayProto.push,
	      slice = ArrayProto.slice,
	      toString = ObjProto.toString,
	      hasOwnProperty = ObjProto.hasOwnProperty;

	  // Modern feature detection.
	  var supportsArrayBuffer = typeof ArrayBuffer !== 'undefined',
	      supportsDataView = typeof DataView !== 'undefined';

	  // All **ECMAScript 5+** native function implementations that we hope to use
	  // are declared here.
	  var nativeIsArray = Array.isArray,
	      nativeKeys = Object.keys,
	      nativeCreate = Object.create,
	      nativeIsView = supportsArrayBuffer && ArrayBuffer.isView;

	  // Create references to these builtin functions because we override them.
	  var _isNaN = isNaN,
	      _isFinite = isFinite;

	  // Keys in IE < 9 that won't be iterated by `for key in ...` and thus missed.
	  var hasEnumBug = !{toString: null}.propertyIsEnumerable('toString');
	  var nonEnumerableProps = ['valueOf', 'isPrototypeOf', 'toString',
	    'propertyIsEnumerable', 'hasOwnProperty', 'toLocaleString'];

	  // The largest integer that can be represented exactly.
	  var MAX_ARRAY_INDEX = Math.pow(2, 53) - 1;

	  // Some functions take a variable number of arguments, or a few expected
	  // arguments at the beginning and then a variable number of values to operate
	  // on. This helper accumulates all remaining arguments past the function’s
	  // argument length (or an explicit `startIndex`), into an array that becomes
	  // the last argument. Similar to ES6’s "rest parameter".
	  function restArguments(func, startIndex) {
	    startIndex = startIndex == null ? func.length - 1 : +startIndex;
	    return function() {
	      var length = Math.max(arguments.length - startIndex, 0),
	          rest = Array(length),
	          index = 0;
	      for (; index < length; index++) {
	        rest[index] = arguments[index + startIndex];
	      }
	      switch (startIndex) {
	        case 0: return func.call(this, rest);
	        case 1: return func.call(this, arguments[0], rest);
	        case 2: return func.call(this, arguments[0], arguments[1], rest);
	      }
	      var args = Array(startIndex + 1);
	      for (index = 0; index < startIndex; index++) {
	        args[index] = arguments[index];
	      }
	      args[startIndex] = rest;
	      return func.apply(this, args);
	    };
	  }

	  // Is a given variable an object?
	  function isObject(obj) {
	    var type = typeof obj;
	    return type === 'function' || (type === 'object' && !!obj);
	  }

	  // Is a given value equal to null?
	  function isNull(obj) {
	    return obj === null;
	  }

	  // Is a given variable undefined?
	  function isUndefined(obj) {
	    return obj === void 0;
	  }

	  // Is a given value a boolean?
	  function isBoolean(obj) {
	    return obj === true || obj === false || toString.call(obj) === '[object Boolean]';
	  }

	  // Is a given value a DOM element?
	  function isElement(obj) {
	    return !!(obj && obj.nodeType === 1);
	  }

	  // Internal function for creating a `toString`-based type tester.
	  function tagTester(name) {
	    var tag = '[object ' + name + ']';
	    return function(obj) {
	      return toString.call(obj) === tag;
	    };
	  }

	  var isString = tagTester('String');

	  var isNumber = tagTester('Number');

	  var isDate = tagTester('Date');

	  var isRegExp = tagTester('RegExp');

	  var isError = tagTester('Error');

	  var isSymbol = tagTester('Symbol');

	  var isArrayBuffer = tagTester('ArrayBuffer');

	  var isFunction = tagTester('Function');

	  // Optimize `isFunction` if appropriate. Work around some `typeof` bugs in old
	  // v8, IE 11 (#1621), Safari 8 (#1929), and PhantomJS (#2236).
	  var nodelist = root.document && root.document.childNodes;
	  if (typeof /./ != 'function' && typeof Int8Array != 'object' && typeof nodelist != 'function') {
	    isFunction = function(obj) {
	      return typeof obj == 'function' || false;
	    };
	  }

	  var isFunction$1 = isFunction;

	  var hasObjectTag = tagTester('Object');

	  // In IE 10 - Edge 13, `DataView` has string tag `'[object Object]'`.
	  // In IE 11, the most common among them, this problem also applies to
	  // `Map`, `WeakMap` and `Set`.
	  var hasStringTagBug = (
	        supportsDataView && hasObjectTag(new DataView(new ArrayBuffer(8)))
	      ),
	      isIE11 = (typeof Map !== 'undefined' && hasObjectTag(new Map));

	  var isDataView = tagTester('DataView');

	  // In IE 10 - Edge 13, we need a different heuristic
	  // to determine whether an object is a `DataView`.
	  function ie10IsDataView(obj) {
	    return obj != null && isFunction$1(obj.getInt8) && isArrayBuffer(obj.buffer);
	  }

	  var isDataView$1 = (hasStringTagBug ? ie10IsDataView : isDataView);

	  // Is a given value an array?
	  // Delegates to ECMA5's native `Array.isArray`.
	  var isArray = nativeIsArray || tagTester('Array');

	  // Internal function to check whether `key` is an own property name of `obj`.
	  function has$1(obj, key) {
	    return obj != null && hasOwnProperty.call(obj, key);
	  }

	  var isArguments = tagTester('Arguments');

	  // Define a fallback version of the method in browsers (ahem, IE < 9), where
	  // there isn't any inspectable "Arguments" type.
	  (function() {
	    if (!isArguments(arguments)) {
	      isArguments = function(obj) {
	        return has$1(obj, 'callee');
	      };
	    }
	  }());

	  var isArguments$1 = isArguments;

	  // Is a given object a finite number?
	  function isFinite$1(obj) {
	    return !isSymbol(obj) && _isFinite(obj) && !isNaN(parseFloat(obj));
	  }

	  // Is the given value `NaN`?
	  function isNaN$1(obj) {
	    return isNumber(obj) && _isNaN(obj);
	  }

	  // Predicate-generating function. Often useful outside of Underscore.
	  function constant(value) {
	    return function() {
	      return value;
	    };
	  }

	  // Common internal logic for `isArrayLike` and `isBufferLike`.
	  function createSizePropertyCheck(getSizeProperty) {
	    return function(collection) {
	      var sizeProperty = getSizeProperty(collection);
	      return typeof sizeProperty == 'number' && sizeProperty >= 0 && sizeProperty <= MAX_ARRAY_INDEX;
	    }
	  }

	  // Internal helper to generate a function to obtain property `key` from `obj`.
	  function shallowProperty(key) {
	    return function(obj) {
	      return obj == null ? void 0 : obj[key];
	    };
	  }

	  // Internal helper to obtain the `byteLength` property of an object.
	  var getByteLength = shallowProperty('byteLength');

	  // Internal helper to determine whether we should spend extensive checks against
	  // `ArrayBuffer` et al.
	  var isBufferLike = createSizePropertyCheck(getByteLength);

	  // Is a given value a typed array?
	  var typedArrayPattern = /\[object ((I|Ui)nt(8|16|32)|Float(32|64)|Uint8Clamped|Big(I|Ui)nt64)Array\]/;
	  function isTypedArray(obj) {
	    // `ArrayBuffer.isView` is the most future-proof, so use it when available.
	    // Otherwise, fall back on the above regular expression.
	    return nativeIsView ? (nativeIsView(obj) && !isDataView$1(obj)) :
	                  isBufferLike(obj) && typedArrayPattern.test(toString.call(obj));
	  }

	  var isTypedArray$1 = supportsArrayBuffer ? isTypedArray : constant(false);

	  // Internal helper to obtain the `length` property of an object.
	  var getLength = shallowProperty('length');

	  // Internal helper to create a simple lookup structure.
	  // `collectNonEnumProps` used to depend on `_.contains`, but this led to
	  // circular imports. `emulatedSet` is a one-off solution that only works for
	  // arrays of strings.
	  function emulatedSet(keys) {
	    var hash = {};
	    for (var l = keys.length, i = 0; i < l; ++i) hash[keys[i]] = true;
	    return {
	      contains: function(key) { return hash[key] === true; },
	      push: function(key) {
	        hash[key] = true;
	        return keys.push(key);
	      }
	    };
	  }

	  // Internal helper. Checks `keys` for the presence of keys in IE < 9 that won't
	  // be iterated by `for key in ...` and thus missed. Extends `keys` in place if
	  // needed.
	  function collectNonEnumProps(obj, keys) {
	    keys = emulatedSet(keys);
	    var nonEnumIdx = nonEnumerableProps.length;
	    var constructor = obj.constructor;
	    var proto = (isFunction$1(constructor) && constructor.prototype) || ObjProto;

	    // Constructor is a special case.
	    var prop = 'constructor';
	    if (has$1(obj, prop) && !keys.contains(prop)) keys.push(prop);

	    while (nonEnumIdx--) {
	      prop = nonEnumerableProps[nonEnumIdx];
	      if (prop in obj && obj[prop] !== proto[prop] && !keys.contains(prop)) {
	        keys.push(prop);
	      }
	    }
	  }

	  // Retrieve the names of an object's own properties.
	  // Delegates to **ECMAScript 5**'s native `Object.keys`.
	  function keys(obj) {
	    if (!isObject(obj)) return [];
	    if (nativeKeys) return nativeKeys(obj);
	    var keys = [];
	    for (var key in obj) if (has$1(obj, key)) keys.push(key);
	    // Ahem, IE < 9.
	    if (hasEnumBug) collectNonEnumProps(obj, keys);
	    return keys;
	  }

	  // Is a given array, string, or object empty?
	  // An "empty" object has no enumerable own-properties.
	  function isEmpty(obj) {
	    if (obj == null) return true;
	    // Skip the more expensive `toString`-based type checks if `obj` has no
	    // `.length`.
	    var length = getLength(obj);
	    if (typeof length == 'number' && (
	      isArray(obj) || isString(obj) || isArguments$1(obj)
	    )) return length === 0;
	    return getLength(keys(obj)) === 0;
	  }

	  // Returns whether an object has a given set of `key:value` pairs.
	  function isMatch(object, attrs) {
	    var _keys = keys(attrs), length = _keys.length;
	    if (object == null) return !length;
	    var obj = Object(object);
	    for (var i = 0; i < length; i++) {
	      var key = _keys[i];
	      if (attrs[key] !== obj[key] || !(key in obj)) return false;
	    }
	    return true;
	  }

	  // If Underscore is called as a function, it returns a wrapped object that can
	  // be used OO-style. This wrapper holds altered versions of all functions added
	  // through `_.mixin`. Wrapped objects may be chained.
	  function _$1(obj) {
	    if (obj instanceof _$1) return obj;
	    if (!(this instanceof _$1)) return new _$1(obj);
	    this._wrapped = obj;
	  }

	  _$1.VERSION = VERSION;

	  // Extracts the result from a wrapped and chained object.
	  _$1.prototype.value = function() {
	    return this._wrapped;
	  };

	  // Provide unwrapping proxies for some methods used in engine operations
	  // such as arithmetic and JSON stringification.
	  _$1.prototype.valueOf = _$1.prototype.toJSON = _$1.prototype.value;

	  _$1.prototype.toString = function() {
	    return String(this._wrapped);
	  };

	  // Internal function to wrap or shallow-copy an ArrayBuffer,
	  // typed array or DataView to a new view, reusing the buffer.
	  function toBufferView(bufferSource) {
	    return new Uint8Array(
	      bufferSource.buffer || bufferSource,
	      bufferSource.byteOffset || 0,
	      getByteLength(bufferSource)
	    );
	  }

	  // We use this string twice, so give it a name for minification.
	  var tagDataView = '[object DataView]';

	  // Internal recursive comparison function for `_.isEqual`.
	  function eq(a, b, aStack, bStack) {
	    // Identical objects are equal. `0 === -0`, but they aren't identical.
	    // See the [Harmony `egal` proposal](https://wiki.ecmascript.org/doku.php?id=harmony:egal).
	    if (a === b) return a !== 0 || 1 / a === 1 / b;
	    // `null` or `undefined` only equal to itself (strict comparison).
	    if (a == null || b == null) return false;
	    // `NaN`s are equivalent, but non-reflexive.
	    if (a !== a) return b !== b;
	    // Exhaust primitive checks
	    var type = typeof a;
	    if (type !== 'function' && type !== 'object' && typeof b != 'object') return false;
	    return deepEq(a, b, aStack, bStack);
	  }

	  // Internal recursive comparison function for `_.isEqual`.
	  function deepEq(a, b, aStack, bStack) {
	    // Unwrap any wrapped objects.
	    if (a instanceof _$1) a = a._wrapped;
	    if (b instanceof _$1) b = b._wrapped;
	    // Compare `[[Class]]` names.
	    var className = toString.call(a);
	    if (className !== toString.call(b)) return false;
	    // Work around a bug in IE 10 - Edge 13.
	    if (hasStringTagBug && className == '[object Object]' && isDataView$1(a)) {
	      if (!isDataView$1(b)) return false;
	      className = tagDataView;
	    }
	    switch (className) {
	      // These types are compared by value.
	      case '[object RegExp]':
	        // RegExps are coerced to strings for comparison (Note: '' + /a/i === '/a/i')
	      case '[object String]':
	        // Primitives and their corresponding object wrappers are equivalent; thus, `"5"` is
	        // equivalent to `new String("5")`.
	        return '' + a === '' + b;
	      case '[object Number]':
	        // `NaN`s are equivalent, but non-reflexive.
	        // Object(NaN) is equivalent to NaN.
	        if (+a !== +a) return +b !== +b;
	        // An `egal` comparison is performed for other numeric values.
	        return +a === 0 ? 1 / +a === 1 / b : +a === +b;
	      case '[object Date]':
	      case '[object Boolean]':
	        // Coerce dates and booleans to numeric primitive values. Dates are compared by their
	        // millisecond representations. Note that invalid dates with millisecond representations
	        // of `NaN` are not equivalent.
	        return +a === +b;
	      case '[object Symbol]':
	        return SymbolProto.valueOf.call(a) === SymbolProto.valueOf.call(b);
	      case '[object ArrayBuffer]':
	      case tagDataView:
	        // Coerce to typed array so we can fall through.
	        return deepEq(toBufferView(a), toBufferView(b), aStack, bStack);
	    }

	    var areArrays = className === '[object Array]';
	    if (!areArrays && isTypedArray$1(a)) {
	        var byteLength = getByteLength(a);
	        if (byteLength !== getByteLength(b)) return false;
	        if (a.buffer === b.buffer && a.byteOffset === b.byteOffset) return true;
	        areArrays = true;
	    }
	    if (!areArrays) {
	      if (typeof a != 'object' || typeof b != 'object') return false;

	      // Objects with different constructors are not equivalent, but `Object`s or `Array`s
	      // from different frames are.
	      var aCtor = a.constructor, bCtor = b.constructor;
	      if (aCtor !== bCtor && !(isFunction$1(aCtor) && aCtor instanceof aCtor &&
	                               isFunction$1(bCtor) && bCtor instanceof bCtor)
	                          && ('constructor' in a && 'constructor' in b)) {
	        return false;
	      }
	    }
	    // Assume equality for cyclic structures. The algorithm for detecting cyclic
	    // structures is adapted from ES 5.1 section 15.12.3, abstract operation `JO`.

	    // Initializing stack of traversed objects.
	    // It's done here since we only need them for objects and arrays comparison.
	    aStack = aStack || [];
	    bStack = bStack || [];
	    var length = aStack.length;
	    while (length--) {
	      // Linear search. Performance is inversely proportional to the number of
	      // unique nested structures.
	      if (aStack[length] === a) return bStack[length] === b;
	    }

	    // Add the first object to the stack of traversed objects.
	    aStack.push(a);
	    bStack.push(b);

	    // Recursively compare objects and arrays.
	    if (areArrays) {
	      // Compare array lengths to determine if a deep comparison is necessary.
	      length = a.length;
	      if (length !== b.length) return false;
	      // Deep compare the contents, ignoring non-numeric properties.
	      while (length--) {
	        if (!eq(a[length], b[length], aStack, bStack)) return false;
	      }
	    } else {
	      // Deep compare objects.
	      var _keys = keys(a), key;
	      length = _keys.length;
	      // Ensure that both objects contain the same number of properties before comparing deep equality.
	      if (keys(b).length !== length) return false;
	      while (length--) {
	        // Deep compare each member
	        key = _keys[length];
	        if (!(has$1(b, key) && eq(a[key], b[key], aStack, bStack))) return false;
	      }
	    }
	    // Remove the first object from the stack of traversed objects.
	    aStack.pop();
	    bStack.pop();
	    return true;
	  }

	  // Perform a deep comparison to check if two objects are equal.
	  function isEqual(a, b) {
	    return eq(a, b);
	  }

	  // Retrieve all the enumerable property names of an object.
	  function allKeys(obj) {
	    if (!isObject(obj)) return [];
	    var keys = [];
	    for (var key in obj) keys.push(key);
	    // Ahem, IE < 9.
	    if (hasEnumBug) collectNonEnumProps(obj, keys);
	    return keys;
	  }

	  // Since the regular `Object.prototype.toString` type tests don't work for
	  // some types in IE 11, we use a fingerprinting heuristic instead, based
	  // on the methods. It's not great, but it's the best we got.
	  // The fingerprint method lists are defined below.
	  function ie11fingerprint(methods) {
	    var length = getLength(methods);
	    return function(obj) {
	      if (obj == null) return false;
	      // `Map`, `WeakMap` and `Set` have no enumerable keys.
	      var keys = allKeys(obj);
	      if (getLength(keys)) return false;
	      for (var i = 0; i < length; i++) {
	        if (!isFunction$1(obj[methods[i]])) return false;
	      }
	      // If we are testing against `WeakMap`, we need to ensure that
	      // `obj` doesn't have a `forEach` method in order to distinguish
	      // it from a regular `Map`.
	      return methods !== weakMapMethods || !isFunction$1(obj[forEachName]);
	    };
	  }

	  // In the interest of compact minification, we write
	  // each string in the fingerprints only once.
	  var forEachName = 'forEach',
	      hasName = 'has',
	      commonInit = ['clear', 'delete'],
	      mapTail = ['get', hasName, 'set'];

	  // `Map`, `WeakMap` and `Set` each have slightly different
	  // combinations of the above sublists.
	  var mapMethods = commonInit.concat(forEachName, mapTail),
	      weakMapMethods = commonInit.concat(mapTail),
	      setMethods = ['add'].concat(commonInit, forEachName, hasName);

	  var isMap = isIE11 ? ie11fingerprint(mapMethods) : tagTester('Map');

	  var isWeakMap = isIE11 ? ie11fingerprint(weakMapMethods) : tagTester('WeakMap');

	  var isSet = isIE11 ? ie11fingerprint(setMethods) : tagTester('Set');

	  var isWeakSet = tagTester('WeakSet');

	  // Retrieve the values of an object's properties.
	  function values(obj) {
	    var _keys = keys(obj);
	    var length = _keys.length;
	    var values = Array(length);
	    for (var i = 0; i < length; i++) {
	      values[i] = obj[_keys[i]];
	    }
	    return values;
	  }

	  // Convert an object into a list of `[key, value]` pairs.
	  // The opposite of `_.object` with one argument.
	  function pairs(obj) {
	    var _keys = keys(obj);
	    var length = _keys.length;
	    var pairs = Array(length);
	    for (var i = 0; i < length; i++) {
	      pairs[i] = [_keys[i], obj[_keys[i]]];
	    }
	    return pairs;
	  }

	  // Invert the keys and values of an object. The values must be serializable.
	  function invert(obj) {
	    var result = {};
	    var _keys = keys(obj);
	    for (var i = 0, length = _keys.length; i < length; i++) {
	      result[obj[_keys[i]]] = _keys[i];
	    }
	    return result;
	  }

	  // Return a sorted list of the function names available on the object.
	  function functions(obj) {
	    var names = [];
	    for (var key in obj) {
	      if (isFunction$1(obj[key])) names.push(key);
	    }
	    return names.sort();
	  }

	  // An internal function for creating assigner functions.
	  function createAssigner(keysFunc, defaults) {
	    return function(obj) {
	      var length = arguments.length;
	      if (defaults) obj = Object(obj);
	      if (length < 2 || obj == null) return obj;
	      for (var index = 1; index < length; index++) {
	        var source = arguments[index],
	            keys = keysFunc(source),
	            l = keys.length;
	        for (var i = 0; i < l; i++) {
	          var key = keys[i];
	          if (!defaults || obj[key] === void 0) obj[key] = source[key];
	        }
	      }
	      return obj;
	    };
	  }

	  // Extend a given object with all the properties in passed-in object(s).
	  var extend = createAssigner(allKeys);

	  // Assigns a given object with all the own properties in the passed-in
	  // object(s).
	  // (https://developer.mozilla.org/docs/Web/JavaScript/Reference/Global_Objects/Object/assign)
	  var extendOwn = createAssigner(keys);

	  // Fill in a given object with default properties.
	  var defaults = createAssigner(allKeys, true);

	  // Create a naked function reference for surrogate-prototype-swapping.
	  function ctor() {
	    return function(){};
	  }

	  // An internal function for creating a new object that inherits from another.
	  function baseCreate(prototype) {
	    if (!isObject(prototype)) return {};
	    if (nativeCreate) return nativeCreate(prototype);
	    var Ctor = ctor();
	    Ctor.prototype = prototype;
	    var result = new Ctor;
	    Ctor.prototype = null;
	    return result;
	  }

	  // Creates an object that inherits from the given prototype object.
	  // If additional properties are provided then they will be added to the
	  // created object.
	  function create(prototype, props) {
	    var result = baseCreate(prototype);
	    if (props) extendOwn(result, props);
	    return result;
	  }

	  // Create a (shallow-cloned) duplicate of an object.
	  function clone(obj) {
	    if (!isObject(obj)) return obj;
	    return isArray(obj) ? obj.slice() : extend({}, obj);
	  }

	  // Invokes `interceptor` with the `obj` and then returns `obj`.
	  // The primary purpose of this method is to "tap into" a method chain, in
	  // order to perform operations on intermediate results within the chain.
	  function tap(obj, interceptor) {
	    interceptor(obj);
	    return obj;
	  }

	  // Normalize a (deep) property `path` to array.
	  // Like `_.iteratee`, this function can be customized.
	  function toPath$1(path) {
	    return isArray(path) ? path : [path];
	  }
	  _$1.toPath = toPath$1;

	  // Internal wrapper for `_.toPath` to enable minification.
	  // Similar to `cb` for `_.iteratee`.
	  function toPath(path) {
	    return _$1.toPath(path);
	  }

	  // Internal function to obtain a nested property in `obj` along `path`.
	  function deepGet(obj, path) {
	    var length = path.length;
	    for (var i = 0; i < length; i++) {
	      if (obj == null) return void 0;
	      obj = obj[path[i]];
	    }
	    return length ? obj : void 0;
	  }

	  // Get the value of the (deep) property on `path` from `object`.
	  // If any property in `path` does not exist or if the value is
	  // `undefined`, return `defaultValue` instead.
	  // The `path` is normalized through `_.toPath`.
	  function get(object, path, defaultValue) {
	    var value = deepGet(object, toPath(path));
	    return isUndefined(value) ? defaultValue : value;
	  }

	  // Shortcut function for checking if an object has a given property directly on
	  // itself (in other words, not on a prototype). Unlike the internal `has`
	  // function, this public version can also traverse nested properties.
	  function has(obj, path) {
	    path = toPath(path);
	    var length = path.length;
	    for (var i = 0; i < length; i++) {
	      var key = path[i];
	      if (!has$1(obj, key)) return false;
	      obj = obj[key];
	    }
	    return !!length;
	  }

	  // Keep the identity function around for default iteratees.
	  function identity(value) {
	    return value;
	  }

	  // Returns a predicate for checking whether an object has a given set of
	  // `key:value` pairs.
	  function matcher(attrs) {
	    attrs = extendOwn({}, attrs);
	    return function(obj) {
	      return isMatch(obj, attrs);
	    };
	  }

	  // Creates a function that, when passed an object, will traverse that object’s
	  // properties down the given `path`, specified as an array of keys or indices.
	  function property(path) {
	    path = toPath(path);
	    return function(obj) {
	      return deepGet(obj, path);
	    };
	  }

	  // Internal function that returns an efficient (for current engines) version
	  // of the passed-in callback, to be repeatedly applied in other Underscore
	  // functions.
	  function optimizeCb(func, context, argCount) {
	    if (context === void 0) return func;
	    switch (argCount == null ? 3 : argCount) {
	      case 1: return function(value) {
	        return func.call(context, value);
	      };
	      // The 2-argument case is omitted because we’re not using it.
	      case 3: return function(value, index, collection) {
	        return func.call(context, value, index, collection);
	      };
	      case 4: return function(accumulator, value, index, collection) {
	        return func.call(context, accumulator, value, index, collection);
	      };
	    }
	    return function() {
	      return func.apply(context, arguments);
	    };
	  }

	  // An internal function to generate callbacks that can be applied to each
	  // element in a collection, returning the desired result — either `_.identity`,
	  // an arbitrary callback, a property matcher, or a property accessor.
	  function baseIteratee(value, context, argCount) {
	    if (value == null) return identity;
	    if (isFunction$1(value)) return optimizeCb(value, context, argCount);
	    if (isObject(value) && !isArray(value)) return matcher(value);
	    return property(value);
	  }

	  // External wrapper for our callback generator. Users may customize
	  // `_.iteratee` if they want additional predicate/iteratee shorthand styles.
	  // This abstraction hides the internal-only `argCount` argument.
	  function iteratee(value, context) {
	    return baseIteratee(value, context, Infinity);
	  }
	  _$1.iteratee = iteratee;

	  // The function we call internally to generate a callback. It invokes
	  // `_.iteratee` if overridden, otherwise `baseIteratee`.
	  function cb(value, context, argCount) {
	    if (_$1.iteratee !== iteratee) return _$1.iteratee(value, context);
	    return baseIteratee(value, context, argCount);
	  }

	  // Returns the results of applying the `iteratee` to each element of `obj`.
	  // In contrast to `_.map` it returns an object.
	  function mapObject(obj, iteratee, context) {
	    iteratee = cb(iteratee, context);
	    var _keys = keys(obj),
	        length = _keys.length,
	        results = {};
	    for (var index = 0; index < length; index++) {
	      var currentKey = _keys[index];
	      results[currentKey] = iteratee(obj[currentKey], currentKey, obj);
	    }
	    return results;
	  }

	  // Predicate-generating function. Often useful outside of Underscore.
	  function noop(){}

	  // Generates a function for a given object that returns a given property.
	  function propertyOf(obj) {
	    if (obj == null) return noop;
	    return function(path) {
	      return get(obj, path);
	    };
	  }

	  // Run a function **n** times.
	  function times(n, iteratee, context) {
	    var accum = Array(Math.max(0, n));
	    iteratee = optimizeCb(iteratee, context, 1);
	    for (var i = 0; i < n; i++) accum[i] = iteratee(i);
	    return accum;
	  }

	  // Return a random integer between `min` and `max` (inclusive).
	  function random(min, max) {
	    if (max == null) {
	      max = min;
	      min = 0;
	    }
	    return min + Math.floor(Math.random() * (max - min + 1));
	  }

	  // A (possibly faster) way to get the current timestamp as an integer.
	  var now = Date.now || function() {
	    return new Date().getTime();
	  };

	  // Internal helper to generate functions for escaping and unescaping strings
	  // to/from HTML interpolation.
	  function createEscaper(map) {
	    var escaper = function(match) {
	      return map[match];
	    };
	    // Regexes for identifying a key that needs to be escaped.
	    var source = '(?:' + keys(map).join('|') + ')';
	    var testRegexp = RegExp(source);
	    var replaceRegexp = RegExp(source, 'g');
	    return function(string) {
	      string = string == null ? '' : '' + string;
	      return testRegexp.test(string) ? string.replace(replaceRegexp, escaper) : string;
	    };
	  }

	  // Internal list of HTML entities for escaping.
	  var escapeMap = {
	    '&': '&amp;',
	    '<': '&lt;',
	    '>': '&gt;',
	    '"': '&quot;',
	    "'": '&#x27;',
	    '`': '&#x60;'
	  };

	  // Function for escaping strings to HTML interpolation.
	  var _escape = createEscaper(escapeMap);

	  // Internal list of HTML entities for unescaping.
	  var unescapeMap = invert(escapeMap);

	  // Function for unescaping strings from HTML interpolation.
	  var _unescape = createEscaper(unescapeMap);

	  // By default, Underscore uses ERB-style template delimiters. Change the
	  // following template settings to use alternative delimiters.
	  var templateSettings = _$1.templateSettings = {
	    evaluate: /<%([\s\S]+?)%>/g,
	    interpolate: /<%=([\s\S]+?)%>/g,
	    escape: /<%-([\s\S]+?)%>/g
	  };

	  // When customizing `_.templateSettings`, if you don't want to define an
	  // interpolation, evaluation or escaping regex, we need one that is
	  // guaranteed not to match.
	  var noMatch = /(.)^/;

	  // Certain characters need to be escaped so that they can be put into a
	  // string literal.
	  var escapes = {
	    "'": "'",
	    '\\': '\\',
	    '\r': 'r',
	    '\n': 'n',
	    '\u2028': 'u2028',
	    '\u2029': 'u2029'
	  };

	  var escapeRegExp = /\\|'|\r|\n|\u2028|\u2029/g;

	  function escapeChar(match) {
	    return '\\' + escapes[match];
	  }

	  // In order to prevent third-party code injection through
	  // `_.templateSettings.variable`, we test it against the following regular
	  // expression. It is intentionally a bit more liberal than just matching valid
	  // identifiers, but still prevents possible loopholes through defaults or
	  // destructuring assignment.
	  var bareIdentifier = /^\s*(\w|\$)+\s*$/;

	  // JavaScript micro-templating, similar to John Resig's implementation.
	  // Underscore templating handles arbitrary delimiters, preserves whitespace,
	  // and correctly escapes quotes within interpolated code.
	  // NB: `oldSettings` only exists for backwards compatibility.
	  function template(text, settings, oldSettings) {
	    if (!settings && oldSettings) settings = oldSettings;
	    settings = defaults({}, settings, _$1.templateSettings);

	    // Combine delimiters into one regular expression via alternation.
	    var matcher = RegExp([
	      (settings.escape || noMatch).source,
	      (settings.interpolate || noMatch).source,
	      (settings.evaluate || noMatch).source
	    ].join('|') + '|$', 'g');

	    // Compile the template source, escaping string literals appropriately.
	    var index = 0;
	    var source = "__p+='";
	    text.replace(matcher, function(match, escape, interpolate, evaluate, offset) {
	      source += text.slice(index, offset).replace(escapeRegExp, escapeChar);
	      index = offset + match.length;

	      if (escape) {
	        source += "'+\n((__t=(" + escape + "))==null?'':_.escape(__t))+\n'";
	      } else if (interpolate) {
	        source += "'+\n((__t=(" + interpolate + "))==null?'':__t)+\n'";
	      } else if (evaluate) {
	        source += "';\n" + evaluate + "\n__p+='";
	      }

	      // Adobe VMs need the match returned to produce the correct offset.
	      return match;
	    });
	    source += "';\n";

	    var argument = settings.variable;
	    if (argument) {
	      // Insure against third-party code injection. (CVE-2021-23358)
	      if (!bareIdentifier.test(argument)) throw new Error(
	        'variable is not a bare identifier: ' + argument
	      );
	    } else {
	      // If a variable is not specified, place data values in local scope.
	      source = 'with(obj||{}){\n' + source + '}\n';
	      argument = 'obj';
	    }

	    source = "var __t,__p='',__j=Array.prototype.join," +
	      "print=function(){__p+=__j.call(arguments,'');};\n" +
	      source + 'return __p;\n';

	    var render;
	    try {
	      render = new Function(argument, '_', source);
	    } catch (e) {
	      e.source = source;
	      throw e;
	    }

	    var template = function(data) {
	      return render.call(this, data, _$1);
	    };

	    // Provide the compiled source as a convenience for precompilation.
	    template.source = 'function(' + argument + '){\n' + source + '}';

	    return template;
	  }

	  // Traverses the children of `obj` along `path`. If a child is a function, it
	  // is invoked with its parent as context. Returns the value of the final
	  // child, or `fallback` if any child is undefined.
	  function result(obj, path, fallback) {
	    path = toPath(path);
	    var length = path.length;
	    if (!length) {
	      return isFunction$1(fallback) ? fallback.call(obj) : fallback;
	    }
	    for (var i = 0; i < length; i++) {
	      var prop = obj == null ? void 0 : obj[path[i]];
	      if (prop === void 0) {
	        prop = fallback;
	        i = length; // Ensure we don't continue iterating.
	      }
	      obj = isFunction$1(prop) ? prop.call(obj) : prop;
	    }
	    return obj;
	  }

	  // Generate a unique integer id (unique within the entire client session).
	  // Useful for temporary DOM ids.
	  var idCounter = 0;
	  function uniqueId(prefix) {
	    var id = ++idCounter + '';
	    return prefix ? prefix + id : id;
	  }

	  // Start chaining a wrapped Underscore object.
	  function chain(obj) {
	    var instance = _$1(obj);
	    instance._chain = true;
	    return instance;
	  }

	  // Internal function to execute `sourceFunc` bound to `context` with optional
	  // `args`. Determines whether to execute a function as a constructor or as a
	  // normal function.
	  function executeBound(sourceFunc, boundFunc, context, callingContext, args) {
	    if (!(callingContext instanceof boundFunc)) return sourceFunc.apply(context, args);
	    var self = baseCreate(sourceFunc.prototype);
	    var result = sourceFunc.apply(self, args);
	    if (isObject(result)) return result;
	    return self;
	  }

	  // Partially apply a function by creating a version that has had some of its
	  // arguments pre-filled, without changing its dynamic `this` context. `_` acts
	  // as a placeholder by default, allowing any combination of arguments to be
	  // pre-filled. Set `_.partial.placeholder` for a custom placeholder argument.
	  var partial = restArguments(function(func, boundArgs) {
	    var placeholder = partial.placeholder;
	    var bound = function() {
	      var position = 0, length = boundArgs.length;
	      var args = Array(length);
	      for (var i = 0; i < length; i++) {
	        args[i] = boundArgs[i] === placeholder ? arguments[position++] : boundArgs[i];
	      }
	      while (position < arguments.length) args.push(arguments[position++]);
	      return executeBound(func, bound, this, this, args);
	    };
	    return bound;
	  });

	  partial.placeholder = _$1;

	  // Create a function bound to a given object (assigning `this`, and arguments,
	  // optionally).
	  var bind = restArguments(function(func, context, args) {
	    if (!isFunction$1(func)) throw new TypeError('Bind must be called on a function');
	    var bound = restArguments(function(callArgs) {
	      return executeBound(func, bound, context, this, args.concat(callArgs));
	    });
	    return bound;
	  });

	  // Internal helper for collection methods to determine whether a collection
	  // should be iterated as an array or as an object.
	  // Related: https://people.mozilla.org/~jorendorff/es6-draft.html#sec-tolength
	  // Avoids a very nasty iOS 8 JIT bug on ARM-64. #2094
	  var isArrayLike = createSizePropertyCheck(getLength);

	  // Internal implementation of a recursive `flatten` function.
	  function flatten$1(input, depth, strict, output) {
	    output = output || [];
	    if (!depth && depth !== 0) {
	      depth = Infinity;
	    } else if (depth <= 0) {
	      return output.concat(input);
	    }
	    var idx = output.length;
	    for (var i = 0, length = getLength(input); i < length; i++) {
	      var value = input[i];
	      if (isArrayLike(value) && (isArray(value) || isArguments$1(value))) {
	        // Flatten current level of array or arguments object.
	        if (depth > 1) {
	          flatten$1(value, depth - 1, strict, output);
	          idx = output.length;
	        } else {
	          var j = 0, len = value.length;
	          while (j < len) output[idx++] = value[j++];
	        }
	      } else if (!strict) {
	        output[idx++] = value;
	      }
	    }
	    return output;
	  }

	  // Bind a number of an object's methods to that object. Remaining arguments
	  // are the method names to be bound. Useful for ensuring that all callbacks
	  // defined on an object belong to it.
	  var bindAll = restArguments(function(obj, keys) {
	    keys = flatten$1(keys, false, false);
	    var index = keys.length;
	    if (index < 1) throw new Error('bindAll must be passed function names');
	    while (index--) {
	      var key = keys[index];
	      obj[key] = bind(obj[key], obj);
	    }
	    return obj;
	  });

	  // Memoize an expensive function by storing its results.
	  function memoize(func, hasher) {
	    var memoize = function(key) {
	      var cache = memoize.cache;
	      var address = '' + (hasher ? hasher.apply(this, arguments) : key);
	      if (!has$1(cache, address)) cache[address] = func.apply(this, arguments);
	      return cache[address];
	    };
	    memoize.cache = {};
	    return memoize;
	  }

	  // Delays a function for the given number of milliseconds, and then calls
	  // it with the arguments supplied.
	  var delay = restArguments(function(func, wait, args) {
	    return setTimeout(function() {
	      return func.apply(null, args);
	    }, wait);
	  });

	  // Defers a function, scheduling it to run after the current call stack has
	  // cleared.
	  var defer = partial(delay, _$1, 1);

	  // Returns a function, that, when invoked, will only be triggered at most once
	  // during a given window of time. Normally, the throttled function will run
	  // as much as it can, without ever going more than once per `wait` duration;
	  // but if you'd like to disable the execution on the leading edge, pass
	  // `{leading: false}`. To disable execution on the trailing edge, ditto.
	  function throttle(func, wait, options) {
	    var timeout, context, args, result;
	    var previous = 0;
	    if (!options) options = {};

	    var later = function() {
	      previous = options.leading === false ? 0 : now();
	      timeout = null;
	      result = func.apply(context, args);
	      if (!timeout) context = args = null;
	    };

	    var throttled = function() {
	      var _now = now();
	      if (!previous && options.leading === false) previous = _now;
	      var remaining = wait - (_now - previous);
	      context = this;
	      args = arguments;
	      if (remaining <= 0 || remaining > wait) {
	        if (timeout) {
	          clearTimeout(timeout);
	          timeout = null;
	        }
	        previous = _now;
	        result = func.apply(context, args);
	        if (!timeout) context = args = null;
	      } else if (!timeout && options.trailing !== false) {
	        timeout = setTimeout(later, remaining);
	      }
	      return result;
	    };

	    throttled.cancel = function() {
	      clearTimeout(timeout);
	      previous = 0;
	      timeout = context = args = null;
	    };

	    return throttled;
	  }

	  // When a sequence of calls of the returned function ends, the argument
	  // function is triggered. The end of a sequence is defined by the `wait`
	  // parameter. If `immediate` is passed, the argument function will be
	  // triggered at the beginning of the sequence instead of at the end.
	  function debounce(func, wait, immediate) {
	    var timeout, previous, args, result, context;

	    var later = function() {
	      var passed = now() - previous;
	      if (wait > passed) {
	        timeout = setTimeout(later, wait - passed);
	      } else {
	        timeout = null;
	        if (!immediate) result = func.apply(context, args);
	        // This check is needed because `func` can recursively invoke `debounced`.
	        if (!timeout) args = context = null;
	      }
	    };

	    var debounced = restArguments(function(_args) {
	      context = this;
	      args = _args;
	      previous = now();
	      if (!timeout) {
	        timeout = setTimeout(later, wait);
	        if (immediate) result = func.apply(context, args);
	      }
	      return result;
	    });

	    debounced.cancel = function() {
	      clearTimeout(timeout);
	      timeout = args = context = null;
	    };

	    return debounced;
	  }

	  // Returns the first function passed as an argument to the second,
	  // allowing you to adjust arguments, run code before and after, and
	  // conditionally execute the original function.
	  function wrap(func, wrapper) {
	    return partial(wrapper, func);
	  }

	  // Returns a negated version of the passed-in predicate.
	  function negate(predicate) {
	    return function() {
	      return !predicate.apply(this, arguments);
	    };
	  }

	  // Returns a function that is the composition of a list of functions, each
	  // consuming the return value of the function that follows.
	  function compose() {
	    var args = arguments;
	    var start = args.length - 1;
	    return function() {
	      var i = start;
	      var result = args[start].apply(this, arguments);
	      while (i--) result = args[i].call(this, result);
	      return result;
	    };
	  }

	  // Returns a function that will only be executed on and after the Nth call.
	  function after(times, func) {
	    return function() {
	      if (--times < 1) {
	        return func.apply(this, arguments);
	      }
	    };
	  }

	  // Returns a function that will only be executed up to (but not including) the
	  // Nth call.
	  function before(times, func) {
	    var memo;
	    return function() {
	      if (--times > 0) {
	        memo = func.apply(this, arguments);
	      }
	      if (times <= 1) func = null;
	      return memo;
	    };
	  }

	  // Returns a function that will be executed at most one time, no matter how
	  // often you call it. Useful for lazy initialization.
	  var once = partial(before, 2);

	  // Returns the first key on an object that passes a truth test.
	  function findKey(obj, predicate, context) {
	    predicate = cb(predicate, context);
	    var _keys = keys(obj), key;
	    for (var i = 0, length = _keys.length; i < length; i++) {
	      key = _keys[i];
	      if (predicate(obj[key], key, obj)) return key;
	    }
	  }

	  // Internal function to generate `_.findIndex` and `_.findLastIndex`.
	  function createPredicateIndexFinder(dir) {
	    return function(array, predicate, context) {
	      predicate = cb(predicate, context);
	      var length = getLength(array);
	      var index = dir > 0 ? 0 : length - 1;
	      for (; index >= 0 && index < length; index += dir) {
	        if (predicate(array[index], index, array)) return index;
	      }
	      return -1;
	    };
	  }

	  // Returns the first index on an array-like that passes a truth test.
	  var findIndex = createPredicateIndexFinder(1);

	  // Returns the last index on an array-like that passes a truth test.
	  var findLastIndex = createPredicateIndexFinder(-1);

	  // Use a comparator function to figure out the smallest index at which
	  // an object should be inserted so as to maintain order. Uses binary search.
	  function sortedIndex(array, obj, iteratee, context) {
	    iteratee = cb(iteratee, context, 1);
	    var value = iteratee(obj);
	    var low = 0, high = getLength(array);
	    while (low < high) {
	      var mid = Math.floor((low + high) / 2);
	      if (iteratee(array[mid]) < value) low = mid + 1; else high = mid;
	    }
	    return low;
	  }

	  // Internal function to generate the `_.indexOf` and `_.lastIndexOf` functions.
	  function createIndexFinder(dir, predicateFind, sortedIndex) {
	    return function(array, item, idx) {
	      var i = 0, length = getLength(array);
	      if (typeof idx == 'number') {
	        if (dir > 0) {
	          i = idx >= 0 ? idx : Math.max(idx + length, i);
	        } else {
	          length = idx >= 0 ? Math.min(idx + 1, length) : idx + length + 1;
	        }
	      } else if (sortedIndex && idx && length) {
	        idx = sortedIndex(array, item);
	        return array[idx] === item ? idx : -1;
	      }
	      if (item !== item) {
	        idx = predicateFind(slice.call(array, i, length), isNaN$1);
	        return idx >= 0 ? idx + i : -1;
	      }
	      for (idx = dir > 0 ? i : length - 1; idx >= 0 && idx < length; idx += dir) {
	        if (array[idx] === item) return idx;
	      }
	      return -1;
	    };
	  }

	  // Return the position of the first occurrence of an item in an array,
	  // or -1 if the item is not included in the array.
	  // If the array is large and already in sort order, pass `true`
	  // for **isSorted** to use binary search.
	  var indexOf = createIndexFinder(1, findIndex, sortedIndex);

	  // Return the position of the last occurrence of an item in an array,
	  // or -1 if the item is not included in the array.
	  var lastIndexOf = createIndexFinder(-1, findLastIndex);

	  // Return the first value which passes a truth test.
	  function find(obj, predicate, context) {
	    var keyFinder = isArrayLike(obj) ? findIndex : findKey;
	    var key = keyFinder(obj, predicate, context);
	    if (key !== void 0 && key !== -1) return obj[key];
	  }

	  // Convenience version of a common use case of `_.find`: getting the first
	  // object containing specific `key:value` pairs.
	  function findWhere(obj, attrs) {
	    return find(obj, matcher(attrs));
	  }

	  // The cornerstone for collection functions, an `each`
	  // implementation, aka `forEach`.
	  // Handles raw objects in addition to array-likes. Treats all
	  // sparse array-likes as if they were dense.
	  function each(obj, iteratee, context) {
	    iteratee = optimizeCb(iteratee, context);
	    var i, length;
	    if (isArrayLike(obj)) {
	      for (i = 0, length = obj.length; i < length; i++) {
	        iteratee(obj[i], i, obj);
	      }
	    } else {
	      var _keys = keys(obj);
	      for (i = 0, length = _keys.length; i < length; i++) {
	        iteratee(obj[_keys[i]], _keys[i], obj);
	      }
	    }
	    return obj;
	  }

	  // Return the results of applying the iteratee to each element.
	  function map(obj, iteratee, context) {
	    iteratee = cb(iteratee, context);
	    var _keys = !isArrayLike(obj) && keys(obj),
	        length = (_keys || obj).length,
	        results = Array(length);
	    for (var index = 0; index < length; index++) {
	      var currentKey = _keys ? _keys[index] : index;
	      results[index] = iteratee(obj[currentKey], currentKey, obj);
	    }
	    return results;
	  }

	  // Internal helper to create a reducing function, iterating left or right.
	  function createReduce(dir) {
	    // Wrap code that reassigns argument variables in a separate function than
	    // the one that accesses `arguments.length` to avoid a perf hit. (#1991)
	    var reducer = function(obj, iteratee, memo, initial) {
	      var _keys = !isArrayLike(obj) && keys(obj),
	          length = (_keys || obj).length,
	          index = dir > 0 ? 0 : length - 1;
	      if (!initial) {
	        memo = obj[_keys ? _keys[index] : index];
	        index += dir;
	      }
	      for (; index >= 0 && index < length; index += dir) {
	        var currentKey = _keys ? _keys[index] : index;
	        memo = iteratee(memo, obj[currentKey], currentKey, obj);
	      }
	      return memo;
	    };

	    return function(obj, iteratee, memo, context) {
	      var initial = arguments.length >= 3;
	      return reducer(obj, optimizeCb(iteratee, context, 4), memo, initial);
	    };
	  }

	  // **Reduce** builds up a single result from a list of values, aka `inject`,
	  // or `foldl`.
	  var reduce = createReduce(1);

	  // The right-associative version of reduce, also known as `foldr`.
	  var reduceRight = createReduce(-1);

	  // Return all the elements that pass a truth test.
	  function filter(obj, predicate, context) {
	    var results = [];
	    predicate = cb(predicate, context);
	    each(obj, function(value, index, list) {
	      if (predicate(value, index, list)) results.push(value);
	    });
	    return results;
	  }

	  // Return all the elements for which a truth test fails.
	  function reject(obj, predicate, context) {
	    return filter(obj, negate(cb(predicate)), context);
	  }

	  // Determine whether all of the elements pass a truth test.
	  function every(obj, predicate, context) {
	    predicate = cb(predicate, context);
	    var _keys = !isArrayLike(obj) && keys(obj),
	        length = (_keys || obj).length;
	    for (var index = 0; index < length; index++) {
	      var currentKey = _keys ? _keys[index] : index;
	      if (!predicate(obj[currentKey], currentKey, obj)) return false;
	    }
	    return true;
	  }

	  // Determine if at least one element in the object passes a truth test.
	  function some(obj, predicate, context) {
	    predicate = cb(predicate, context);
	    var _keys = !isArrayLike(obj) && keys(obj),
	        length = (_keys || obj).length;
	    for (var index = 0; index < length; index++) {
	      var currentKey = _keys ? _keys[index] : index;
	      if (predicate(obj[currentKey], currentKey, obj)) return true;
	    }
	    return false;
	  }

	  // Determine if the array or object contains a given item (using `===`).
	  function contains(obj, item, fromIndex, guard) {
	    if (!isArrayLike(obj)) obj = values(obj);
	    if (typeof fromIndex != 'number' || guard) fromIndex = 0;
	    return indexOf(obj, item, fromIndex) >= 0;
	  }

	  // Invoke a method (with arguments) on every item in a collection.
	  var invoke = restArguments(function(obj, path, args) {
	    var contextPath, func;
	    if (isFunction$1(path)) {
	      func = path;
	    } else {
	      path = toPath(path);
	      contextPath = path.slice(0, -1);
	      path = path[path.length - 1];
	    }
	    return map(obj, function(context) {
	      var method = func;
	      if (!method) {
	        if (contextPath && contextPath.length) {
	          context = deepGet(context, contextPath);
	        }
	        if (context == null) return void 0;
	        method = context[path];
	      }
	      return method == null ? method : method.apply(context, args);
	    });
	  });

	  // Convenience version of a common use case of `_.map`: fetching a property.
	  function pluck(obj, key) {
	    return map(obj, property(key));
	  }

	  // Convenience version of a common use case of `_.filter`: selecting only
	  // objects containing specific `key:value` pairs.
	  function where(obj, attrs) {
	    return filter(obj, matcher(attrs));
	  }

	  // Return the maximum element (or element-based computation).
	  function max(obj, iteratee, context) {
	    var result = -Infinity, lastComputed = -Infinity,
	        value, computed;
	    if (iteratee == null || (typeof iteratee == 'number' && typeof obj[0] != 'object' && obj != null)) {
	      obj = isArrayLike(obj) ? obj : values(obj);
	      for (var i = 0, length = obj.length; i < length; i++) {
	        value = obj[i];
	        if (value != null && value > result) {
	          result = value;
	        }
	      }
	    } else {
	      iteratee = cb(iteratee, context);
	      each(obj, function(v, index, list) {
	        computed = iteratee(v, index, list);
	        if (computed > lastComputed || (computed === -Infinity && result === -Infinity)) {
	          result = v;
	          lastComputed = computed;
	        }
	      });
	    }
	    return result;
	  }

	  // Return the minimum element (or element-based computation).
	  function min(obj, iteratee, context) {
	    var result = Infinity, lastComputed = Infinity,
	        value, computed;
	    if (iteratee == null || (typeof iteratee == 'number' && typeof obj[0] != 'object' && obj != null)) {
	      obj = isArrayLike(obj) ? obj : values(obj);
	      for (var i = 0, length = obj.length; i < length; i++) {
	        value = obj[i];
	        if (value != null && value < result) {
	          result = value;
	        }
	      }
	    } else {
	      iteratee = cb(iteratee, context);
	      each(obj, function(v, index, list) {
	        computed = iteratee(v, index, list);
	        if (computed < lastComputed || (computed === Infinity && result === Infinity)) {
	          result = v;
	          lastComputed = computed;
	        }
	      });
	    }
	    return result;
	  }

	  // Safely create a real, live array from anything iterable.
	  var reStrSymbol = /[^\ud800-\udfff]|[\ud800-\udbff][\udc00-\udfff]|[\ud800-\udfff]/g;
	  function toArray(obj) {
	    if (!obj) return [];
	    if (isArray(obj)) return slice.call(obj);
	    if (isString(obj)) {
	      // Keep surrogate pair characters together.
	      return obj.match(reStrSymbol);
	    }
	    if (isArrayLike(obj)) return map(obj, identity);
	    return values(obj);
	  }

	  // Sample **n** random values from a collection using the modern version of the
	  // [Fisher-Yates shuffle](https://en.wikipedia.org/wiki/Fisher–Yates_shuffle).
	  // If **n** is not specified, returns a single random element.
	  // The internal `guard` argument allows it to work with `_.map`.
	  function sample(obj, n, guard) {
	    if (n == null || guard) {
	      if (!isArrayLike(obj)) obj = values(obj);
	      return obj[random(obj.length - 1)];
	    }
	    var sample = toArray(obj);
	    var length = getLength(sample);
	    n = Math.max(Math.min(n, length), 0);
	    var last = length - 1;
	    for (var index = 0; index < n; index++) {
	      var rand = random(index, last);
	      var temp = sample[index];
	      sample[index] = sample[rand];
	      sample[rand] = temp;
	    }
	    return sample.slice(0, n);
	  }

	  // Shuffle a collection.
	  function shuffle(obj) {
	    return sample(obj, Infinity);
	  }

	  // Sort the object's values by a criterion produced by an iteratee.
	  function sortBy(obj, iteratee, context) {
	    var index = 0;
	    iteratee = cb(iteratee, context);
	    return pluck(map(obj, function(value, key, list) {
	      return {
	        value: value,
	        index: index++,
	        criteria: iteratee(value, key, list)
	      };
	    }).sort(function(left, right) {
	      var a = left.criteria;
	      var b = right.criteria;
	      if (a !== b) {
	        if (a > b || a === void 0) return 1;
	        if (a < b || b === void 0) return -1;
	      }
	      return left.index - right.index;
	    }), 'value');
	  }

	  // An internal function used for aggregate "group by" operations.
	  function group(behavior, partition) {
	    return function(obj, iteratee, context) {
	      var result = partition ? [[], []] : {};
	      iteratee = cb(iteratee, context);
	      each(obj, function(value, index) {
	        var key = iteratee(value, index, obj);
	        behavior(result, value, key);
	      });
	      return result;
	    };
	  }

	  // Groups the object's values by a criterion. Pass either a string attribute
	  // to group by, or a function that returns the criterion.
	  var groupBy = group(function(result, value, key) {
	    if (has$1(result, key)) result[key].push(value); else result[key] = [value];
	  });

	  // Indexes the object's values by a criterion, similar to `_.groupBy`, but for
	  // when you know that your index values will be unique.
	  var indexBy = group(function(result, value, key) {
	    result[key] = value;
	  });

	  // Counts instances of an object that group by a certain criterion. Pass
	  // either a string attribute to count by, or a function that returns the
	  // criterion.
	  var countBy = group(function(result, value, key) {
	    if (has$1(result, key)) result[key]++; else result[key] = 1;
	  });

	  // Split a collection into two arrays: one whose elements all pass the given
	  // truth test, and one whose elements all do not pass the truth test.
	  var partition = group(function(result, value, pass) {
	    result[pass ? 0 : 1].push(value);
	  }, true);

	  // Return the number of elements in a collection.
	  function size(obj) {
	    if (obj == null) return 0;
	    return isArrayLike(obj) ? obj.length : keys(obj).length;
	  }

	  // Internal `_.pick` helper function to determine whether `key` is an enumerable
	  // property name of `obj`.
	  function keyInObj(value, key, obj) {
	    return key in obj;
	  }

	  // Return a copy of the object only containing the allowed properties.
	  var pick = restArguments(function(obj, keys) {
	    var result = {}, iteratee = keys[0];
	    if (obj == null) return result;
	    if (isFunction$1(iteratee)) {
	      if (keys.length > 1) iteratee = optimizeCb(iteratee, keys[1]);
	      keys = allKeys(obj);
	    } else {
	      iteratee = keyInObj;
	      keys = flatten$1(keys, false, false);
	      obj = Object(obj);
	    }
	    for (var i = 0, length = keys.length; i < length; i++) {
	      var key = keys[i];
	      var value = obj[key];
	      if (iteratee(value, key, obj)) result[key] = value;
	    }
	    return result;
	  });

	  // Return a copy of the object without the disallowed properties.
	  var omit = restArguments(function(obj, keys) {
	    var iteratee = keys[0], context;
	    if (isFunction$1(iteratee)) {
	      iteratee = negate(iteratee);
	      if (keys.length > 1) context = keys[1];
	    } else {
	      keys = map(flatten$1(keys, false, false), String);
	      iteratee = function(value, key) {
	        return !contains(keys, key);
	      };
	    }
	    return pick(obj, iteratee, context);
	  });

	  // Returns everything but the last entry of the array. Especially useful on
	  // the arguments object. Passing **n** will return all the values in
	  // the array, excluding the last N.
	  function initial(array, n, guard) {
	    return slice.call(array, 0, Math.max(0, array.length - (n == null || guard ? 1 : n)));
	  }

	  // Get the first element of an array. Passing **n** will return the first N
	  // values in the array. The **guard** check allows it to work with `_.map`.
	  function first(array, n, guard) {
	    if (array == null || array.length < 1) return n == null || guard ? void 0 : [];
	    if (n == null || guard) return array[0];
	    return initial(array, array.length - n);
	  }

	  // Returns everything but the first entry of the `array`. Especially useful on
	  // the `arguments` object. Passing an **n** will return the rest N values in the
	  // `array`.
	  function rest(array, n, guard) {
	    return slice.call(array, n == null || guard ? 1 : n);
	  }

	  // Get the last element of an array. Passing **n** will return the last N
	  // values in the array.
	  function last(array, n, guard) {
	    if (array == null || array.length < 1) return n == null || guard ? void 0 : [];
	    if (n == null || guard) return array[array.length - 1];
	    return rest(array, Math.max(0, array.length - n));
	  }

	  // Trim out all falsy values from an array.
	  function compact(array) {
	    return filter(array, Boolean);
	  }

	  // Flatten out an array, either recursively (by default), or up to `depth`.
	  // Passing `true` or `false` as `depth` means `1` or `Infinity`, respectively.
	  function flatten(array, depth) {
	    return flatten$1(array, depth, false);
	  }

	  // Take the difference between one array and a number of other arrays.
	  // Only the elements present in just the first array will remain.
	  var difference = restArguments(function(array, rest) {
	    rest = flatten$1(rest, true, true);
	    return filter(array, function(value){
	      return !contains(rest, value);
	    });
	  });

	  // Return a version of the array that does not contain the specified value(s).
	  var without = restArguments(function(array, otherArrays) {
	    return difference(array, otherArrays);
	  });

	  // Produce a duplicate-free version of the array. If the array has already
	  // been sorted, you have the option of using a faster algorithm.
	  // The faster algorithm will not work with an iteratee if the iteratee
	  // is not a one-to-one function, so providing an iteratee will disable
	  // the faster algorithm.
	  function uniq(array, isSorted, iteratee, context) {
	    if (!isBoolean(isSorted)) {
	      context = iteratee;
	      iteratee = isSorted;
	      isSorted = false;
	    }
	    if (iteratee != null) iteratee = cb(iteratee, context);
	    var result = [];
	    var seen = [];
	    for (var i = 0, length = getLength(array); i < length; i++) {
	      var value = array[i],
	          computed = iteratee ? iteratee(value, i, array) : value;
	      if (isSorted && !iteratee) {
	        if (!i || seen !== computed) result.push(value);
	        seen = computed;
	      } else if (iteratee) {
	        if (!contains(seen, computed)) {
	          seen.push(computed);
	          result.push(value);
	        }
	      } else if (!contains(result, value)) {
	        result.push(value);
	      }
	    }
	    return result;
	  }

	  // Produce an array that contains the union: each distinct element from all of
	  // the passed-in arrays.
	  var union = restArguments(function(arrays) {
	    return uniq(flatten$1(arrays, true, true));
	  });

	  // Produce an array that contains every item shared between all the
	  // passed-in arrays.
	  function intersection(array) {
	    var result = [];
	    var argsLength = arguments.length;
	    for (var i = 0, length = getLength(array); i < length; i++) {
	      var item = array[i];
	      if (contains(result, item)) continue;
	      var j;
	      for (j = 1; j < argsLength; j++) {
	        if (!contains(arguments[j], item)) break;
	      }
	      if (j === argsLength) result.push(item);
	    }
	    return result;
	  }

	  // Complement of zip. Unzip accepts an array of arrays and groups
	  // each array's elements on shared indices.
	  function unzip(array) {
	    var length = (array && max(array, getLength).length) || 0;
	    var result = Array(length);

	    for (var index = 0; index < length; index++) {
	      result[index] = pluck(array, index);
	    }
	    return result;
	  }

	  // Zip together multiple lists into a single array -- elements that share
	  // an index go together.
	  var zip = restArguments(unzip);

	  // Converts lists into objects. Pass either a single array of `[key, value]`
	  // pairs, or two parallel arrays of the same length -- one of keys, and one of
	  // the corresponding values. Passing by pairs is the reverse of `_.pairs`.
	  function object(list, values) {
	    var result = {};
	    for (var i = 0, length = getLength(list); i < length; i++) {
	      if (values) {
	        result[list[i]] = values[i];
	      } else {
	        result[list[i][0]] = list[i][1];
	      }
	    }
	    return result;
	  }

	  // Generate an integer Array containing an arithmetic progression. A port of
	  // the native Python `range()` function. See
	  // [the Python documentation](https://docs.python.org/library/functions.html#range).
	  function range(start, stop, step) {
	    if (stop == null) {
	      stop = start || 0;
	      start = 0;
	    }
	    if (!step) {
	      step = stop < start ? -1 : 1;
	    }

	    var length = Math.max(Math.ceil((stop - start) / step), 0);
	    var range = Array(length);

	    for (var idx = 0; idx < length; idx++, start += step) {
	      range[idx] = start;
	    }

	    return range;
	  }

	  // Chunk a single array into multiple arrays, each containing `count` or fewer
	  // items.
	  function chunk(array, count) {
	    if (count == null || count < 1) return [];
	    var result = [];
	    var i = 0, length = array.length;
	    while (i < length) {
	      result.push(slice.call(array, i, i += count));
	    }
	    return result;
	  }

	  // Helper function to continue chaining intermediate results.
	  function chainResult(instance, obj) {
	    return instance._chain ? _$1(obj).chain() : obj;
	  }

	  // Add your own custom functions to the Underscore object.
	  function mixin(obj) {
	    each(functions(obj), function(name) {
	      var func = _$1[name] = obj[name];
	      _$1.prototype[name] = function() {
	        var args = [this._wrapped];
	        push.apply(args, arguments);
	        return chainResult(this, func.apply(_$1, args));
	      };
	    });
	    return _$1;
	  }

	  // Add all mutator `Array` functions to the wrapper.
	  each(['pop', 'push', 'reverse', 'shift', 'sort', 'splice', 'unshift'], function(name) {
	    var method = ArrayProto[name];
	    _$1.prototype[name] = function() {
	      var obj = this._wrapped;
	      if (obj != null) {
	        method.apply(obj, arguments);
	        if ((name === 'shift' || name === 'splice') && obj.length === 0) {
	          delete obj[0];
	        }
	      }
	      return chainResult(this, obj);
	    };
	  });

	  // Add all accessor `Array` functions to the wrapper.
	  each(['concat', 'join', 'slice'], function(name) {
	    var method = ArrayProto[name];
	    _$1.prototype[name] = function() {
	      var obj = this._wrapped;
	      if (obj != null) obj = method.apply(obj, arguments);
	      return chainResult(this, obj);
	    };
	  });

	  // Named Exports

	  var allExports = {
	    __proto__: null,
	    VERSION: VERSION,
	    restArguments: restArguments,
	    isObject: isObject,
	    isNull: isNull,
	    isUndefined: isUndefined,
	    isBoolean: isBoolean,
	    isElement: isElement,
	    isString: isString,
	    isNumber: isNumber,
	    isDate: isDate,
	    isRegExp: isRegExp,
	    isError: isError,
	    isSymbol: isSymbol,
	    isArrayBuffer: isArrayBuffer,
	    isDataView: isDataView$1,
	    isArray: isArray,
	    isFunction: isFunction$1,
	    isArguments: isArguments$1,
	    isFinite: isFinite$1,
	    isNaN: isNaN$1,
	    isTypedArray: isTypedArray$1,
	    isEmpty: isEmpty,
	    isMatch: isMatch,
	    isEqual: isEqual,
	    isMap: isMap,
	    isWeakMap: isWeakMap,
	    isSet: isSet,
	    isWeakSet: isWeakSet,
	    keys: keys,
	    allKeys: allKeys,
	    values: values,
	    pairs: pairs,
	    invert: invert,
	    functions: functions,
	    methods: functions,
	    extend: extend,
	    extendOwn: extendOwn,
	    assign: extendOwn,
	    defaults: defaults,
	    create: create,
	    clone: clone,
	    tap: tap,
	    get: get,
	    has: has,
	    mapObject: mapObject,
	    identity: identity,
	    constant: constant,
	    noop: noop,
	    toPath: toPath$1,
	    property: property,
	    propertyOf: propertyOf,
	    matcher: matcher,
	    matches: matcher,
	    times: times,
	    random: random,
	    now: now,
	    escape: _escape,
	    unescape: _unescape,
	    templateSettings: templateSettings,
	    template: template,
	    result: result,
	    uniqueId: uniqueId,
	    chain: chain,
	    iteratee: iteratee,
	    partial: partial,
	    bind: bind,
	    bindAll: bindAll,
	    memoize: memoize,
	    delay: delay,
	    defer: defer,
	    throttle: throttle,
	    debounce: debounce,
	    wrap: wrap,
	    negate: negate,
	    compose: compose,
	    after: after,
	    before: before,
	    once: once,
	    findKey: findKey,
	    findIndex: findIndex,
	    findLastIndex: findLastIndex,
	    sortedIndex: sortedIndex,
	    indexOf: indexOf,
	    lastIndexOf: lastIndexOf,
	    find: find,
	    detect: find,
	    findWhere: findWhere,
	    each: each,
	    forEach: each,
	    map: map,
	    collect: map,
	    reduce: reduce,
	    foldl: reduce,
	    inject: reduce,
	    reduceRight: reduceRight,
	    foldr: reduceRight,
	    filter: filter,
	    select: filter,
	    reject: reject,
	    every: every,
	    all: every,
	    some: some,
	    any: some,
	    contains: contains,
	    includes: contains,
	    include: contains,
	    invoke: invoke,
	    pluck: pluck,
	    where: where,
	    max: max,
	    min: min,
	    shuffle: shuffle,
	    sample: sample,
	    sortBy: sortBy,
	    groupBy: groupBy,
	    indexBy: indexBy,
	    countBy: countBy,
	    partition: partition,
	    toArray: toArray,
	    size: size,
	    pick: pick,
	    omit: omit,
	    first: first,
	    head: first,
	    take: first,
	    initial: initial,
	    last: last,
	    rest: rest,
	    tail: rest,
	    drop: rest,
	    compact: compact,
	    flatten: flatten,
	    without: without,
	    uniq: uniq,
	    unique: uniq,
	    union: union,
	    intersection: intersection,
	    difference: difference,
	    unzip: unzip,
	    transpose: unzip,
	    zip: zip,
	    object: object,
	    range: range,
	    chunk: chunk,
	    mixin: mixin,
	    'default': _$1
	  };

	  // Default Export

	  // Add all of the Underscore functions to the wrapper object.
	  var _ = mixin(allExports);
	  // Legacy Node.js API.
	  _._ = _;

	  return _;

	})));
	//# sourceMappingURL=underscore-umd.js.map

	/* WEBPACK VAR INJECTION */}.call(exports, (function() { return this; }())))

/***/ }),
/* 7 */
/***/ (function(module, exports, __webpack_require__) {

	var __WEBPACK_AMD_DEFINE_FACTORY__, __WEBPACK_AMD_DEFINE_ARRAY__, __WEBPACK_AMD_DEFINE_RESULT__;/*!
	 * jquery.fancytree.js
	 * Tree view control with support for lazy loading and much more.
	 * https://github.com/mar10/fancytree/
	 *
	 * Copyright (c) 2008-2023, Martin Wendt (https://wwWendt.de)
	 * Released under the MIT license
	 * https://github.com/mar10/fancytree/wiki/LicenseInfo
	 *
	 * @version 2.38.3
	 * @date 2023-02-01T20:52:50Z
	 */

	/** Core Fancytree module.
	 */

	// UMD wrapper for the Fancytree core module
	(function (factory) {
		if (true) {
			// AMD. Register as an anonymous module.
			!(__WEBPACK_AMD_DEFINE_ARRAY__ = [__webpack_require__(3), __webpack_require__(8)], __WEBPACK_AMD_DEFINE_FACTORY__ = (factory), __WEBPACK_AMD_DEFINE_RESULT__ = (typeof __WEBPACK_AMD_DEFINE_FACTORY__ === 'function' ? (__WEBPACK_AMD_DEFINE_FACTORY__.apply(exports, __WEBPACK_AMD_DEFINE_ARRAY__)) : __WEBPACK_AMD_DEFINE_FACTORY__), __WEBPACK_AMD_DEFINE_RESULT__ !== undefined && (module.exports = __WEBPACK_AMD_DEFINE_RESULT__));
		} else if (typeof module === "object" && module.exports) {
			// Node/CommonJS
			require("./jquery.fancytree.ui-deps");
			module.exports = factory(require("jquery"));
		} else {
			// Browser globals
			factory(jQuery);
		}
	})(function ($) {
		"use strict";

		// prevent duplicate loading
		if ($.ui && $.ui.fancytree) {
			$.ui.fancytree.warn("Fancytree: ignored duplicate include");
			return;
		}

		/******************************************************************************
		 * Private functions and variables
		 */

		var i,
			attr,
			FT = null, // initialized below
			TEST_IMG = new RegExp(/\.|\//), // strings are considered image urls if they contain '.' or '/'
			REX_HTML = /[&<>"'/]/g, // Escape those characters
			REX_TOOLTIP = /[<>"'/]/g, // Don't escape `&` in tooltips
			RECURSIVE_REQUEST_ERROR = "$recursive_request",
			INVALID_REQUEST_TARGET_ERROR = "$request_target_invalid",
			ENTITY_MAP = {
				"&": "&amp;",
				"<": "&lt;",
				">": "&gt;",
				'"': "&quot;",
				"'": "&#39;",
				"/": "&#x2F;",
			},
			IGNORE_KEYCODES = { 16: true, 17: true, 18: true },
			SPECIAL_KEYCODES = {
				8: "backspace",
				9: "tab",
				10: "return",
				13: "return",
				// 16: null, 17: null, 18: null,  // ignore shift, ctrl, alt
				19: "pause",
				20: "capslock",
				27: "esc",
				32: "space",
				33: "pageup",
				34: "pagedown",
				35: "end",
				36: "home",
				37: "left",
				38: "up",
				39: "right",
				40: "down",
				45: "insert",
				46: "del",
				59: ";",
				61: "=",
				// 91: null, 93: null,  // ignore left and right meta
				96: "0",
				97: "1",
				98: "2",
				99: "3",
				100: "4",
				101: "5",
				102: "6",
				103: "7",
				104: "8",
				105: "9",
				106: "*",
				107: "+",
				109: "-",
				110: ".",
				111: "/",
				112: "f1",
				113: "f2",
				114: "f3",
				115: "f4",
				116: "f5",
				117: "f6",
				118: "f7",
				119: "f8",
				120: "f9",
				121: "f10",
				122: "f11",
				123: "f12",
				144: "numlock",
				145: "scroll",
				173: "-",
				186: ";",
				187: "=",
				188: ",",
				189: "-",
				190: ".",
				191: "/",
				192: "`",
				219: "[",
				220: "\\",
				221: "]",
				222: "'",
			},
			MODIFIERS = {
				16: "shift",
				17: "ctrl",
				18: "alt",
				91: "meta",
				93: "meta",
			},
			MOUSE_BUTTONS = { 0: "", 1: "left", 2: "middle", 3: "right" },
			// Boolean attributes that can be set with equivalent class names in the LI tags
			// Note: v2.23: checkbox and hideCheckbox are *not* in this list
			CLASS_ATTRS =
				"active expanded focus folder lazy radiogroup selected unselectable unselectableIgnore".split(
					" "
				),
			CLASS_ATTR_MAP = {},
			// Top-level Fancytree attributes, that can be set by dict
			TREE_ATTRS = "columns types".split(" "),
			// TREE_ATTR_MAP = {},
			// Top-level FancytreeNode attributes, that can be set by dict
			NODE_ATTRS =
				"checkbox expanded extraClasses folder icon iconTooltip key lazy partsel radiogroup refKey selected statusNodeType title tooltip type unselectable unselectableIgnore unselectableStatus".split(
					" "
				),
			NODE_ATTR_MAP = {},
			// Mapping of lowercase -> real name (because HTML5 data-... attribute only supports lowercase)
			NODE_ATTR_LOWERCASE_MAP = {},
			// Attribute names that should NOT be added to node.data
			NONE_NODE_DATA_MAP = {
				active: true,
				children: true,
				data: true,
				focus: true,
			};

		for (i = 0; i < CLASS_ATTRS.length; i++) {
			CLASS_ATTR_MAP[CLASS_ATTRS[i]] = true;
		}
		for (i = 0; i < NODE_ATTRS.length; i++) {
			attr = NODE_ATTRS[i];
			NODE_ATTR_MAP[attr] = true;
			if (attr !== attr.toLowerCase()) {
				NODE_ATTR_LOWERCASE_MAP[attr.toLowerCase()] = attr;
			}
		}
		// for(i=0; i<TREE_ATTRS.length; i++) {
		// 	TREE_ATTR_MAP[TREE_ATTRS[i]] = true;
		// }

		function _assert(cond, msg) {
			// TODO: see qunit.js extractStacktrace()
			if (!cond) {
				msg = msg ? ": " + msg : "";
				msg = "Fancytree assertion failed" + msg;

				// consoleApply("assert", [!!cond, msg]);

				// #1041: Raised exceptions may not be visible in the browser
				// console if inside promise chains, so we also print directly:
				$.ui.fancytree.error(msg);

				// Throw exception:
				$.error(msg);
			}
		}

		function _hasProp(object, property) {
			return Object.prototype.hasOwnProperty.call(object, property);
		}

		/* Replacement for the deprecated `jQuery.isFunction()`. */
		function _isFunction(obj) {
			return typeof obj === "function";
		}

		/* Replacement for the deprecated `jQuery.trim()`. */
		function _trim(text) {
			return text == null ? "" : text.trim();
		}

		/* Replacement for the deprecated `jQuery.isArray()`. */
		var _isArray = Array.isArray;

		_assert($.ui, "Fancytree requires jQuery UI (http://jqueryui.com)");

		function consoleApply(method, args) {
			var i,
				s,
				fn = window.console ? window.console[method] : null;

			if (fn) {
				try {
					fn.apply(window.console, args);
				} catch (e) {
					// IE 8?
					s = "";
					for (i = 0; i < args.length; i++) {
						s += args[i];
					}
					fn(s);
				}
			}
		}

		/* support: IE8 Polyfil for Date.now() */
		if (!Date.now) {
			Date.now = function now() {
				return new Date().getTime();
			};
		}

		/*Return true if x is a FancytreeNode.*/
		function _isNode(x) {
			return !!(x.tree && x.statusNodeType !== undefined);
		}

		/** Return true if dotted version string is equal or higher than requested version.
		 *
		 * See http://jsfiddle.net/mar10/FjSAN/
		 */
		function isVersionAtLeast(dottedVersion, major, minor, patch) {
			var i,
				v,
				t,
				verParts = $.map(_trim(dottedVersion).split("."), function (e) {
					return parseInt(e, 10);
				}),
				testParts = $.map(
					Array.prototype.slice.call(arguments, 1),
					function (e) {
						return parseInt(e, 10);
					}
				);

			for (i = 0; i < testParts.length; i++) {
				v = verParts[i] || 0;
				t = testParts[i] || 0;
				if (v !== t) {
					return v > t;
				}
			}
			return true;
		}

		/**
		 * Deep-merge a list of objects (but replace array-type options).
		 *
		 * jQuery's $.extend(true, ...) method does a deep merge, that also merges Arrays.
		 * This variant is used to merge extension defaults with user options, and should
		 * merge objects, but override arrays (for example the `triggerStart: [...]` option
		 * of ext-edit). Also `null` values are copied over and not skipped.
		 *
		 * See issue #876
		 *
		 * Example:
		 * _simpleDeepMerge({}, o1, o2);
		 */
		function _simpleDeepMerge() {
			var options,
				name,
				src,
				copy,
				clone,
				target = arguments[0] || {},
				i = 1,
				length = arguments.length;

			// Handle case when target is a string or something (possible in deep copy)
			if (typeof target !== "object" && !_isFunction(target)) {
				target = {};
			}
			if (i === length) {
				throw Error("need at least two args");
			}
			for (; i < length; i++) {
				// Only deal with non-null/undefined values
				if ((options = arguments[i]) != null) {
					// Extend the base object
					for (name in options) {
						if (_hasProp(options, name)) {
							src = target[name];
							copy = options[name];
							// Prevent never-ending loop
							if (target === copy) {
								continue;
							}
							// Recurse if we're merging plain objects
							// (NOTE: unlike $.extend, we don't merge arrays, but replace them)
							if (copy && $.isPlainObject(copy)) {
								clone = src && $.isPlainObject(src) ? src : {};
								// Never move original objects, clone them
								target[name] = _simpleDeepMerge(clone, copy);
								// Don't bring in undefined values
							} else if (copy !== undefined) {
								target[name] = copy;
							}
						}
					}
				}
			}
			// Return the modified object
			return target;
		}

		/** Return a wrapper that calls sub.methodName() and exposes
		 *  this             : tree
		 *  this._local      : tree.ext.EXTNAME
		 *  this._super      : base.methodName.call()
		 *  this._superApply : base.methodName.apply()
		 */
		function _makeVirtualFunction(methodName, tree, base, extension, extName) {
			// $.ui.fancytree.debug("_makeVirtualFunction", methodName, tree, base, extension, extName);
			// if(rexTestSuper && !rexTestSuper.test(func)){
			//     // extension.methodName() doesn't call _super(), so no wrapper required
			//     return func;
			// }
			// Use an immediate function as closure
			var proxy = (function () {
				var prevFunc = tree[methodName], // org. tree method or prev. proxy
					baseFunc = extension[methodName], //
					_local = tree.ext[extName],
					_super = function () {
						return prevFunc.apply(tree, arguments);
					},
					_superApply = function (args) {
						return prevFunc.apply(tree, args);
					};

				// Return the wrapper function
				return function () {
					var prevLocal = tree._local,
						prevSuper = tree._super,
						prevSuperApply = tree._superApply;

					try {
						tree._local = _local;
						tree._super = _super;
						tree._superApply = _superApply;
						return baseFunc.apply(tree, arguments);
					} finally {
						tree._local = prevLocal;
						tree._super = prevSuper;
						tree._superApply = prevSuperApply;
					}
				};
			})(); // end of Immediate Function
			return proxy;
		}

		/**
		 * Subclass `base` by creating proxy functions
		 */
		function _subclassObject(tree, base, extension, extName) {
			// $.ui.fancytree.debug("_subclassObject", tree, base, extension, extName);
			for (var attrName in extension) {
				if (typeof extension[attrName] === "function") {
					if (typeof tree[attrName] === "function") {
						// override existing method
						tree[attrName] = _makeVirtualFunction(
							attrName,
							tree,
							base,
							extension,
							extName
						);
					} else if (attrName.charAt(0) === "_") {
						// Create private methods in tree.ext.EXTENSION namespace
						tree.ext[extName][attrName] = _makeVirtualFunction(
							attrName,
							tree,
							base,
							extension,
							extName
						);
					} else {
						$.error(
							"Could not override tree." +
								attrName +
								". Use prefix '_' to create tree." +
								extName +
								"._" +
								attrName
						);
					}
				} else {
					// Create member variables in tree.ext.EXTENSION namespace
					if (attrName !== "options") {
						tree.ext[extName][attrName] = extension[attrName];
					}
				}
			}
		}

		function _getResolvedPromise(context, argArray) {
			if (context === undefined) {
				return $.Deferred(function () {
					this.resolve();
				}).promise();
			}
			return $.Deferred(function () {
				this.resolveWith(context, argArray);
			}).promise();
		}

		function _getRejectedPromise(context, argArray) {
			if (context === undefined) {
				return $.Deferred(function () {
					this.reject();
				}).promise();
			}
			return $.Deferred(function () {
				this.rejectWith(context, argArray);
			}).promise();
		}

		function _makeResolveFunc(deferred, context) {
			return function () {
				deferred.resolveWith(context);
			};
		}

		function _getElementDataAsDict($el) {
			// Evaluate 'data-NAME' attributes with special treatment for 'data-json'.
			var d = $.extend({}, $el.data()),
				json = d.json;

			delete d.fancytree; // added to container by widget factory (old jQuery UI)
			delete d.uiFancytree; // added to container by widget factory

			if (json) {
				delete d.json;
				// <li data-json='...'> is already returned as object (http://api.jquery.com/data/#data-html5)
				d = $.extend(d, json);
			}
			return d;
		}

		function _escapeTooltip(s) {
			return ("" + s).replace(REX_TOOLTIP, function (s) {
				return ENTITY_MAP[s];
			});
		}

		// TODO: use currying
		function _makeNodeTitleMatcher(s) {
			s = s.toLowerCase();
			return function (node) {
				return node.title.toLowerCase().indexOf(s) >= 0;
			};
		}

		function _makeNodeTitleStartMatcher(s) {
			var reMatch = new RegExp("^" + s, "i");
			return function (node) {
				return reMatch.test(node.title);
			};
		}

		/******************************************************************************
		 * FancytreeNode
		 */

		/**
		 * Creates a new FancytreeNode
		 *
		 * @class FancytreeNode
		 * @classdesc A FancytreeNode represents the hierarchical data model and operations.
		 *
		 * @param {FancytreeNode} parent
		 * @param {NodeData} obj
		 *
		 * @property {Fancytree} tree The tree instance
		 * @property {FancytreeNode} parent The parent node
		 * @property {string} key Node id (must be unique inside the tree)
		 * @property {string} title Display name (may contain HTML)
		 * @property {object} data Contains all extra data that was passed on node creation
		 * @property {FancytreeNode[] | null | undefined} children Array of child nodes.<br>
		 *     For lazy nodes, null or undefined means 'not yet loaded'. Use an empty array
		 *     to define a node that has no children.
		 * @property {boolean} expanded Use isExpanded(), setExpanded() to access this property.
		 * @property {string} extraClasses Additional CSS classes, added to the node's `<span>`.<br>
		 *     Note: use `node.add/remove/toggleClass()` to modify.
		 * @property {boolean} folder Folder nodes have different default icons and click behavior.<br>
		 *     Note: Also non-folders may have children.
		 * @property {string} statusNodeType null for standard nodes. Otherwise type of special system node: 'error', 'loading', 'nodata', or 'paging'.
		 * @property {boolean} lazy True if this node is loaded on demand, i.e. on first expansion.
		 * @property {boolean} selected Use isSelected(), setSelected() to access this property.
		 * @property {string} tooltip Alternative description used as hover popup
		 * @property {string} iconTooltip Description used as hover popup for icon. @since 2.27
		 * @property {string} type Node type, used with tree.types map. @since 2.27
		 */
		function FancytreeNode(parent, obj) {
			var i, l, name, cl;

			this.parent = parent;
			this.tree = parent.tree;
			this.ul = null;
			this.li = null; // <li id='key' ftnode=this> tag
			this.statusNodeType = null; // if this is a temp. node to display the status of its parent
			this._isLoading = false; // if this node itself is loading
			this._error = null; // {message: '...'} if a load error occurred
			this.data = {};

			// TODO: merge this code with node.toDict()
			// copy attributes from obj object
			for (i = 0, l = NODE_ATTRS.length; i < l; i++) {
				name = NODE_ATTRS[i];
				this[name] = obj[name];
			}
			// unselectableIgnore and unselectableStatus imply unselectable
			if (
				this.unselectableIgnore != null ||
				this.unselectableStatus != null
			) {
				this.unselectable = true;
			}
			if (obj.hideCheckbox) {
				$.error(
					"'hideCheckbox' node option was removed in v2.23.0: use 'checkbox: false'"
				);
			}
			// node.data += obj.data
			if (obj.data) {
				$.extend(this.data, obj.data);
			}
			// Copy all other attributes to this.data.NAME
			for (name in obj) {
				if (
					!NODE_ATTR_MAP[name] &&
					(this.tree.options.copyFunctionsToData ||
						!_isFunction(obj[name])) &&
					!NONE_NODE_DATA_MAP[name]
				) {
					// node.data.NAME = obj.NAME
					this.data[name] = obj[name];
				}
			}

			// Fix missing key
			if (this.key == null) {
				// test for null OR undefined
				if (this.tree.options.defaultKey) {
					this.key = "" + this.tree.options.defaultKey(this);
					_assert(this.key, "defaultKey() must return a unique key");
				} else {
					this.key = "_" + FT._nextNodeKey++;
				}
			} else {
				this.key = "" + this.key; // Convert to string (#217)
			}

			// Fix tree.activeNode
			// TODO: not elegant: we use obj.active as marker to set tree.activeNode
			// when loading from a dictionary.
			if (obj.active) {
				_assert(
					this.tree.activeNode === null,
					"only one active node allowed"
				);
				this.tree.activeNode = this;
			}
			if (obj.selected) {
				// #186
				this.tree.lastSelectedNode = this;
			}
			// TODO: handle obj.focus = true

			// Create child nodes
			cl = obj.children;
			if (cl) {
				if (cl.length) {
					this._setChildren(cl);
				} else {
					// if an empty array was passed for a lazy node, keep it, in order to mark it 'loaded'
					this.children = this.lazy ? [] : null;
				}
			} else {
				this.children = null;
			}
			// Add to key/ref map (except for root node)
			//	if( parent ) {
			this.tree._callHook("treeRegisterNode", this.tree, true, this);
			//	}
		}

		FancytreeNode.prototype = /** @lends FancytreeNode# */ {
			/* Return the direct child FancytreeNode with a given key, index. */
			_findDirectChild: function (ptr) {
				var i,
					l,
					cl = this.children;

				if (cl) {
					if (typeof ptr === "string") {
						for (i = 0, l = cl.length; i < l; i++) {
							if (cl[i].key === ptr) {
								return cl[i];
							}
						}
					} else if (typeof ptr === "number") {
						return this.children[ptr];
					} else if (ptr.parent === this) {
						return ptr;
					}
				}
				return null;
			},
			// TODO: activate()
			// TODO: activateSilently()
			/* Internal helper called in recursive addChildren sequence.*/
			_setChildren: function (children) {
				_assert(
					children && (!this.children || this.children.length === 0),
					"only init supported"
				);
				this.children = [];
				for (var i = 0, l = children.length; i < l; i++) {
					this.children.push(new FancytreeNode(this, children[i]));
				}
				this.tree._callHook(
					"treeStructureChanged",
					this.tree,
					"setChildren"
				);
			},
			/**
			 * Append (or insert) a list of child nodes.
			 *
			 * @param {NodeData[]} children array of child node definitions (also single child accepted)
			 * @param {FancytreeNode | string | Integer} [insertBefore] child node (or key or index of such).
			 *     If omitted, the new children are appended.
			 * @returns {FancytreeNode} first child added
			 *
			 * @see FancytreeNode#applyPatch
			 */
			addChildren: function (children, insertBefore) {
				var i,
					l,
					pos,
					origFirstChild = this.getFirstChild(),
					origLastChild = this.getLastChild(),
					firstNode = null,
					nodeList = [];

				if ($.isPlainObject(children)) {
					children = [children];
				}
				if (!this.children) {
					this.children = [];
				}
				for (i = 0, l = children.length; i < l; i++) {
					nodeList.push(new FancytreeNode(this, children[i]));
				}
				firstNode = nodeList[0];
				if (insertBefore == null) {
					this.children = this.children.concat(nodeList);
				} else {
					// Returns null if insertBefore is not a direct child:
					insertBefore = this._findDirectChild(insertBefore);
					pos = $.inArray(insertBefore, this.children);
					_assert(pos >= 0, "insertBefore must be an existing child");
					// insert nodeList after children[pos]
					this.children.splice.apply(
						this.children,
						[pos, 0].concat(nodeList)
					);
				}
				if (origFirstChild && !insertBefore) {
					// #708: Fast path -- don't render every child of root, just the new ones!
					// #723, #729: but only if it's appended to an existing child list
					for (i = 0, l = nodeList.length; i < l; i++) {
						nodeList[i].render(); // New nodes were never rendered before
					}
					// Adjust classes where status may have changed
					// Has a first child
					if (origFirstChild !== this.getFirstChild()) {
						// Different first child -- recompute classes
						origFirstChild.renderStatus();
					}
					if (origLastChild !== this.getLastChild()) {
						// Different last child -- recompute classes
						origLastChild.renderStatus();
					}
				} else if (!this.parent || this.parent.ul || this.tr) {
					// render if the parent was rendered (or this is a root node)
					this.render();
				}
				if (this.tree.options.selectMode === 3) {
					this.fixSelection3FromEndNodes();
				}
				this.triggerModifyChild(
					"add",
					nodeList.length === 1 ? nodeList[0] : null
				);
				return firstNode;
			},
			/**
			 * Add class to node's span tag and to .extraClasses.
			 *
			 * @param {string} className class name
			 *
			 * @since 2.17
			 */
			addClass: function (className) {
				return this.toggleClass(className, true);
			},
			/**
			 * Append or prepend a node, or append a child node.
			 *
			 * This a convenience function that calls addChildren()
			 *
			 * @param {NodeData} node node definition
			 * @param {string} [mode=child] 'before', 'after', 'firstChild', or 'child' ('over' is a synonym for 'child')
			 * @returns {FancytreeNode} new node
			 */
			addNode: function (node, mode) {
				if (mode === undefined || mode === "over") {
					mode = "child";
				}
				switch (mode) {
					case "after":
						return this.getParent().addChildren(
							node,
							this.getNextSibling()
						);
					case "before":
						return this.getParent().addChildren(node, this);
					case "firstChild":
						// Insert before the first child if any
						var insertBefore = this.children ? this.children[0] : null;
						return this.addChildren(node, insertBefore);
					case "child":
					case "over":
						return this.addChildren(node);
				}
				_assert(false, "Invalid mode: " + mode);
			},
			/**Add child status nodes that indicate 'More...', etc.
			 *
			 * This also maintains the node's `partload` property.
			 * @param {boolean|object} node optional node definition. Pass `false` to remove all paging nodes.
			 * @param {string} [mode='child'] 'child'|firstChild'
			 * @since 2.15
			 */
			addPagingNode: function (node, mode) {
				var i, n;

				mode = mode || "child";
				if (node === false) {
					for (i = this.children.length - 1; i >= 0; i--) {
						n = this.children[i];
						if (n.statusNodeType === "paging") {
							this.removeChild(n);
						}
					}
					this.partload = false;
					return;
				}
				node = $.extend(
					{
						title: this.tree.options.strings.moreData,
						statusNodeType: "paging",
						icon: false,
					},
					node
				);
				this.partload = true;
				return this.addNode(node, mode);
			},
			/**
			 * Append new node after this.
			 *
			 * This a convenience function that calls addNode(node, 'after')
			 *
			 * @param {NodeData} node node definition
			 * @returns {FancytreeNode} new node
			 */
			appendSibling: function (node) {
				return this.addNode(node, "after");
			},
			/**
			 * (experimental) Apply a modification (or navigation) operation.
			 *
			 * @param {string} cmd
			 * @param {object} [opts]
			 * @see Fancytree#applyCommand
			 * @since 2.32
			 */
			applyCommand: function (cmd, opts) {
				return this.tree.applyCommand(cmd, this, opts);
			},
			/**
			 * Modify existing child nodes.
			 *
			 * @param {NodePatch} patch
			 * @returns {$.Promise}
			 * @see FancytreeNode#addChildren
			 */
			applyPatch: function (patch) {
				// patch [key, null] means 'remove'
				if (patch === null) {
					this.remove();
					return _getResolvedPromise(this);
				}
				// TODO: make sure that root node is not collapsed or modified
				// copy (most) attributes to node.ATTR or node.data.ATTR
				var name,
					promise,
					v,
					IGNORE_MAP = { children: true, expanded: true, parent: true }; // TODO: should be global

				for (name in patch) {
					if (_hasProp(patch, name)) {
						v = patch[name];
						if (!IGNORE_MAP[name] && !_isFunction(v)) {
							if (NODE_ATTR_MAP[name]) {
								this[name] = v;
							} else {
								this.data[name] = v;
							}
						}
					}
				}
				// Remove and/or create children
				if (_hasProp(patch, "children")) {
					this.removeChildren();
					if (patch.children) {
						// only if not null and not empty list
						// TODO: addChildren instead?
						this._setChildren(patch.children);
					}
					// TODO: how can we APPEND or INSERT child nodes?
				}
				if (this.isVisible()) {
					this.renderTitle();
					this.renderStatus();
				}
				// Expand collapse (final step, since this may be async)
				if (_hasProp(patch, "expanded")) {
					promise = this.setExpanded(patch.expanded);
				} else {
					promise = _getResolvedPromise(this);
				}
				return promise;
			},
			/** Collapse all sibling nodes.
			 * @returns {$.Promise}
			 */
			collapseSiblings: function () {
				return this.tree._callHook("nodeCollapseSiblings", this);
			},
			/** Copy this node as sibling or child of `node`.
			 *
			 * @param {FancytreeNode} node source node
			 * @param {string} [mode=child] 'before' | 'after' | 'child'
			 * @param {Function} [map] callback function(NodeData, FancytreeNode) that could modify the new node
			 * @returns {FancytreeNode} new
			 */
			copyTo: function (node, mode, map) {
				return node.addNode(this.toDict(true, map), mode);
			},
			/** Count direct and indirect children.
			 *
			 * @param {boolean} [deep=true] pass 'false' to only count direct children
			 * @returns {int} number of child nodes
			 */
			countChildren: function (deep) {
				var cl = this.children,
					i,
					l,
					n;
				if (!cl) {
					return 0;
				}
				n = cl.length;
				if (deep !== false) {
					for (i = 0, l = n; i < l; i++) {
						n += cl[i].countChildren();
					}
				}
				return n;
			},
			// TODO: deactivate()
			/** Write to browser console if debugLevel >= 4 (prepending node info)
			 *
			 * @param {*} msg string or object or array of such
			 */
			debug: function (msg) {
				if (this.tree.options.debugLevel >= 4) {
					Array.prototype.unshift.call(arguments, this.toString());
					consoleApply("log", arguments);
				}
			},
			/** Deprecated.
			 * @deprecated since 2014-02-16. Use resetLazy() instead.
			 */
			discard: function () {
				this.warn(
					"FancytreeNode.discard() is deprecated since 2014-02-16. Use .resetLazy() instead."
				);
				return this.resetLazy();
			},
			/** Remove DOM elements for all descendents. May be called on .collapse event
			 * to keep the DOM small.
			 * @param {boolean} [includeSelf=false]
			 */
			discardMarkup: function (includeSelf) {
				var fn = includeSelf ? "nodeRemoveMarkup" : "nodeRemoveChildMarkup";
				this.tree._callHook(fn, this);
			},
			/** Write error to browser console if debugLevel >= 1 (prepending tree info)
			 *
			 * @param {*} msg string or object or array of such
			 */
			error: function (msg) {
				if (this.tree.options.debugLevel >= 1) {
					Array.prototype.unshift.call(arguments, this.toString());
					consoleApply("error", arguments);
				}
			},
			/**Find all nodes that match condition (excluding self).
			 *
			 * @param {string | function(node)} match title string to search for, or a
			 *     callback function that returns `true` if a node is matched.
			 * @returns {FancytreeNode[]} array of nodes (may be empty)
			 */
			findAll: function (match) {
				match = _isFunction(match) ? match : _makeNodeTitleMatcher(match);
				var res = [];
				this.visit(function (n) {
					if (match(n)) {
						res.push(n);
					}
				});
				return res;
			},
			/**Find first node that matches condition (excluding self).
			 *
			 * @param {string | function(node)} match title string to search for, or a
			 *     callback function that returns `true` if a node is matched.
			 * @returns {FancytreeNode} matching node or null
			 * @see FancytreeNode#findAll
			 */
			findFirst: function (match) {
				match = _isFunction(match) ? match : _makeNodeTitleMatcher(match);
				var res = null;
				this.visit(function (n) {
					if (match(n)) {
						res = n;
						return false;
					}
				});
				return res;
			},
			/** Find a node relative to self.
			 *
			 * @param {number|string} where The keyCode that would normally trigger this move,
			 *		or a keyword ('down', 'first', 'last', 'left', 'parent', 'right', 'up').
			 * @returns {FancytreeNode}
			 * @since v2.31
			 */
			findRelatedNode: function (where, includeHidden) {
				return this.tree.findRelatedNode(this, where, includeHidden);
			},
			/* Apply selection state (internal use only) */
			_changeSelectStatusAttrs: function (state) {
				var changed = false,
					opts = this.tree.options,
					unselectable = FT.evalOption(
						"unselectable",
						this,
						this,
						opts,
						false
					),
					unselectableStatus = FT.evalOption(
						"unselectableStatus",
						this,
						this,
						opts,
						undefined
					);

				if (unselectable && unselectableStatus != null) {
					state = unselectableStatus;
				}
				switch (state) {
					case false:
						changed = this.selected || this.partsel;
						this.selected = false;
						this.partsel = false;
						break;
					case true:
						changed = !this.selected || !this.partsel;
						this.selected = true;
						this.partsel = true;
						break;
					case undefined:
						changed = this.selected || !this.partsel;
						this.selected = false;
						this.partsel = true;
						break;
					default:
						_assert(false, "invalid state: " + state);
				}
				// this.debug("fixSelection3AfterLoad() _changeSelectStatusAttrs()", state, changed);
				if (changed) {
					this.renderStatus();
				}
				return changed;
			},
			/**
			 * Fix selection status, after this node was (de)selected in multi-hier mode.
			 * This includes (de)selecting all children.
			 */
			fixSelection3AfterClick: function (callOpts) {
				var flag = this.isSelected();

				// this.debug("fixSelection3AfterClick()");

				this.visit(function (node) {
					node._changeSelectStatusAttrs(flag);
					if (node.radiogroup) {
						// #931: don't (de)select this branch
						return "skip";
					}
				});
				this.fixSelection3FromEndNodes(callOpts);
			},
			/**
			 * Fix selection status for multi-hier mode.
			 * Only end-nodes are considered to update the descendants branch and parents.
			 * Should be called after this node has loaded new children or after
			 * children have been modified using the API.
			 */
			fixSelection3FromEndNodes: function (callOpts) {
				var opts = this.tree.options;

				// this.debug("fixSelection3FromEndNodes()");
				_assert(opts.selectMode === 3, "expected selectMode 3");

				// Visit all end nodes and adjust their parent's `selected` and `partsel`
				// attributes. Return selection state true, false, or undefined.
				function _walk(node) {
					var i,
						l,
						child,
						s,
						state,
						allSelected,
						someSelected,
						unselIgnore,
						unselState,
						children = node.children;

					if (children && children.length) {
						// check all children recursively
						allSelected = true;
						someSelected = false;

						for (i = 0, l = children.length; i < l; i++) {
							child = children[i];
							// the selection state of a node is not relevant; we need the end-nodes
							s = _walk(child);
							// if( !child.unselectableIgnore ) {
							unselIgnore = FT.evalOption(
								"unselectableIgnore",
								child,
								child,
								opts,
								false
							);
							if (!unselIgnore) {
								if (s !== false) {
									someSelected = true;
								}
								if (s !== true) {
									allSelected = false;
								}
							}
						}
						// eslint-disable-next-line no-nested-ternary
						state = allSelected
							? true
							: someSelected
							? undefined
							: false;
					} else {
						// This is an end-node: simply report the status
						unselState = FT.evalOption(
							"unselectableStatus",
							node,
							node,
							opts,
							undefined
						);
						state = unselState == null ? !!node.selected : !!unselState;
					}
					// #939: Keep a `partsel` flag that was explicitly set on a lazy node
					if (
						node.partsel &&
						!node.selected &&
						node.lazy &&
						node.children == null
					) {
						state = undefined;
					}
					node._changeSelectStatusAttrs(state);
					return state;
				}
				_walk(this);

				// Update parent's state
				this.visitParents(function (node) {
					var i,
						l,
						child,
						state,
						unselIgnore,
						unselState,
						children = node.children,
						allSelected = true,
						someSelected = false;

					for (i = 0, l = children.length; i < l; i++) {
						child = children[i];
						unselIgnore = FT.evalOption(
							"unselectableIgnore",
							child,
							child,
							opts,
							false
						);
						if (!unselIgnore) {
							unselState = FT.evalOption(
								"unselectableStatus",
								child,
								child,
								opts,
								undefined
							);
							state =
								unselState == null
									? !!child.selected
									: !!unselState;
							// When fixing the parents, we trust the sibling status (i.e.
							// we don't recurse)
							if (state || child.partsel) {
								someSelected = true;
							}
							if (!state) {
								allSelected = false;
							}
						}
					}
					// eslint-disable-next-line no-nested-ternary
					state = allSelected ? true : someSelected ? undefined : false;
					node._changeSelectStatusAttrs(state);
				});
			},
			// TODO: focus()
			/**
			 * Update node data. If dict contains 'children', then also replace
			 * the hole sub tree.
			 * @param {NodeData} dict
			 *
			 * @see FancytreeNode#addChildren
			 * @see FancytreeNode#applyPatch
			 */
			fromDict: function (dict) {
				// copy all other attributes to this.data.xxx
				for (var name in dict) {
					if (NODE_ATTR_MAP[name]) {
						// node.NAME = dict.NAME
						this[name] = dict[name];
					} else if (name === "data") {
						// node.data += dict.data
						$.extend(this.data, dict.data);
					} else if (
						!_isFunction(dict[name]) &&
						!NONE_NODE_DATA_MAP[name]
					) {
						// node.data.NAME = dict.NAME
						this.data[name] = dict[name];
					}
				}
				if (dict.children) {
					// recursively set children and render
					this.removeChildren();
					this.addChildren(dict.children);
				}
				this.renderTitle();
				/*
				var children = dict.children;
				if(children === undefined){
					this.data = $.extend(this.data, dict);
					this.render();
					return;
				}
				dict = $.extend({}, dict);
				dict.children = undefined;
				this.data = $.extend(this.data, dict);
				this.removeChildren();
				this.addChild(children);
				*/
			},
			/** Return the list of child nodes (undefined for unexpanded lazy nodes).
			 * @returns {FancytreeNode[] | undefined}
			 */
			getChildren: function () {
				if (this.hasChildren() === undefined) {
					// TODO: only required for lazy nodes?
					return undefined; // Lazy node: unloaded, currently loading, or load error
				}
				return this.children;
			},
			/** Return the first child node or null.
			 * @returns {FancytreeNode | null}
			 */
			getFirstChild: function () {
				return this.children ? this.children[0] : null;
			},
			/** Return the 0-based child index.
			 * @returns {int}
			 */
			getIndex: function () {
				// return this.parent.children.indexOf(this);
				return $.inArray(this, this.parent.children); // indexOf doesn't work in IE7
			},
			/** Return the hierarchical child index (1-based, e.g. '3.2.4').
			 * @param {string} [separator="."]
			 * @param {int} [digits=1]
			 * @returns {string}
			 */
			getIndexHier: function (separator, digits) {
				separator = separator || ".";
				var s,
					res = [];
				$.each(this.getParentList(false, true), function (i, o) {
					s = "" + (o.getIndex() + 1);
					if (digits) {
						// prepend leading zeroes
						s = ("0000000" + s).substr(-digits);
					}
					res.push(s);
				});
				return res.join(separator);
			},
			/** Return the parent keys separated by options.keyPathSeparator, e.g. "/id_1/id_17/id_32".
			 *
			 * (Unlike `node.getPath()`, this method prepends a "/" and inverts the first argument.)
			 *
			 * @see FancytreeNode#getPath
			 * @param {boolean} [excludeSelf=false]
			 * @returns {string}
			 */
			getKeyPath: function (excludeSelf) {
				var sep = this.tree.options.keyPathSeparator;

				return sep + this.getPath(!excludeSelf, "key", sep);
			},
			/** Return the last child of this node or null.
			 * @returns {FancytreeNode | null}
			 */
			getLastChild: function () {
				return this.children
					? this.children[this.children.length - 1]
					: null;
			},
			/** Return node depth. 0: System root node, 1: visible top-level node, 2: first sub-level, ... .
			 * @returns {int}
			 */
			getLevel: function () {
				var level = 0,
					dtn = this.parent;
				while (dtn) {
					level++;
					dtn = dtn.parent;
				}
				return level;
			},
			/** Return the successor node (under the same parent) or null.
			 * @returns {FancytreeNode | null}
			 */
			getNextSibling: function () {
				// TODO: use indexOf, if available: (not in IE6)
				if (this.parent) {
					var i,
						l,
						ac = this.parent.children;

					for (i = 0, l = ac.length - 1; i < l; i++) {
						// up to length-2, so next(last) = null
						if (ac[i] === this) {
							return ac[i + 1];
						}
					}
				}
				return null;
			},
			/** Return the parent node (null for the system root node).
			 * @returns {FancytreeNode | null}
			 */
			getParent: function () {
				// TODO: return null for top-level nodes?
				return this.parent;
			},
			/** Return an array of all parent nodes (top-down).
			 * @param {boolean} [includeRoot=false] Include the invisible system root node.
			 * @param {boolean} [includeSelf=false] Include the node itself.
			 * @returns {FancytreeNode[]}
			 */
			getParentList: function (includeRoot, includeSelf) {
				var l = [],
					dtn = includeSelf ? this : this.parent;
				while (dtn) {
					if (includeRoot || dtn.parent) {
						l.unshift(dtn);
					}
					dtn = dtn.parent;
				}
				return l;
			},
			/** Return a string representing the hierachical node path, e.g. "a/b/c".
			 * @param {boolean} [includeSelf=true]
			 * @param {string | function} [part="title"] node property name or callback
			 * @param {string} [separator="/"]
			 * @returns {string}
			 * @since v2.31
			 */
			getPath: function (includeSelf, part, separator) {
				includeSelf = includeSelf !== false;
				part = part || "title";
				separator = separator || "/";

				var val,
					path = [],
					isFunc = _isFunction(part);

				this.visitParents(function (n) {
					if (n.parent) {
						val = isFunc ? part(n) : n[part];
						path.unshift(val);
					}
				}, includeSelf);
				return path.join(separator);
			},
			/** Return the predecessor node (under the same parent) or null.
			 * @returns {FancytreeNode | null}
			 */
			getPrevSibling: function () {
				if (this.parent) {
					var i,
						l,
						ac = this.parent.children;

					for (i = 1, l = ac.length; i < l; i++) {
						// start with 1, so prev(first) = null
						if (ac[i] === this) {
							return ac[i - 1];
						}
					}
				}
				return null;
			},
			/**
			 * Return an array of selected descendant nodes.
			 * @param {boolean} [stopOnParents=false] only return the topmost selected
			 *     node (useful with selectMode 3)
			 * @returns {FancytreeNode[]}
			 */
			getSelectedNodes: function (stopOnParents) {
				var nodeList = [];
				this.visit(function (node) {
					if (node.selected) {
						nodeList.push(node);
						if (stopOnParents === true) {
							return "skip"; // stop processing this branch
						}
					}
				});
				return nodeList;
			},
			/** Return true if node has children. Return undefined if not sure, i.e. the node is lazy and not yet loaded).
			 * @returns {boolean | undefined}
			 */
			hasChildren: function () {
				if (this.lazy) {
					if (this.children == null) {
						// null or undefined: Not yet loaded
						return undefined;
					} else if (this.children.length === 0) {
						// Loaded, but response was empty
						return false;
					} else if (
						this.children.length === 1 &&
						this.children[0].isStatusNode()
					) {
						// Currently loading or load error
						return undefined;
					}
					return true;
				}
				return !!(this.children && this.children.length);
			},
			/**
			 * Return true if node has `className` defined in .extraClasses.
			 *
			 * @param {string} className class name (separate multiple classes by space)
			 * @returns {boolean}
			 *
			 * @since 2.32
			 */
			hasClass: function (className) {
				return (
					(" " + (this.extraClasses || "") + " ").indexOf(
						" " + className + " "
					) >= 0
				);
			},
			/** Return true if node has keyboard focus.
			 * @returns {boolean}
			 */
			hasFocus: function () {
				return this.tree.hasFocus() && this.tree.focusNode === this;
			},
			/** Write to browser console if debugLevel >= 3 (prepending node info)
			 *
			 * @param {*} msg string or object or array of such
			 */
			info: function (msg) {
				if (this.tree.options.debugLevel >= 3) {
					Array.prototype.unshift.call(arguments, this.toString());
					consoleApply("info", arguments);
				}
			},
			/** Return true if node is active (see also FancytreeNode#isSelected).
			 * @returns {boolean}
			 */
			isActive: function () {
				return this.tree.activeNode === this;
			},
			/** Return true if node is vertically below `otherNode`, i.e. rendered in a subsequent row.
			 * @param {FancytreeNode} otherNode
			 * @returns {boolean}
			 * @since 2.28
			 */
			isBelowOf: function (otherNode) {
				return this.getIndexHier(".", 5) > otherNode.getIndexHier(".", 5);
			},
			/** Return true if node is a direct child of otherNode.
			 * @param {FancytreeNode} otherNode
			 * @returns {boolean}
			 */
			isChildOf: function (otherNode) {
				return this.parent && this.parent === otherNode;
			},
			/** Return true, if node is a direct or indirect sub node of otherNode.
			 * @param {FancytreeNode} otherNode
			 * @returns {boolean}
			 */
			isDescendantOf: function (otherNode) {
				if (!otherNode || otherNode.tree !== this.tree) {
					return false;
				}
				var p = this.parent;
				while (p) {
					if (p === otherNode) {
						return true;
					}
					if (p === p.parent) {
						$.error("Recursive parent link: " + p);
					}
					p = p.parent;
				}
				return false;
			},
			/** Return true if node is expanded.
			 * @returns {boolean}
			 */
			isExpanded: function () {
				return !!this.expanded;
			},
			/** Return true if node is the first node of its parent's children.
			 * @returns {boolean}
			 */
			isFirstSibling: function () {
				var p = this.parent;
				return !p || p.children[0] === this;
			},
			/** Return true if node is a folder, i.e. has the node.folder attribute set.
			 * @returns {boolean}
			 */
			isFolder: function () {
				return !!this.folder;
			},
			/** Return true if node is the last node of its parent's children.
			 * @returns {boolean}
			 */
			isLastSibling: function () {
				var p = this.parent;
				return !p || p.children[p.children.length - 1] === this;
			},
			/** Return true if node is lazy (even if data was already loaded)
			 * @returns {boolean}
			 */
			isLazy: function () {
				return !!this.lazy;
			},
			/** Return true if node is lazy and loaded. For non-lazy nodes always return true.
			 * @returns {boolean}
			 */
			isLoaded: function () {
				return !this.lazy || this.hasChildren() !== undefined; // Also checks if the only child is a status node
			},
			/** Return true if children are currently beeing loaded, i.e. a Ajax request is pending.
			 * @returns {boolean}
			 */
			isLoading: function () {
				return !!this._isLoading;
			},
			/*
			 * @deprecated since v2.4.0:  Use isRootNode() instead
			 */
			isRoot: function () {
				return this.isRootNode();
			},
			/** Return true if node is partially selected (tri-state).
			 * @returns {boolean}
			 * @since 2.23
			 */
			isPartsel: function () {
				return !this.selected && !!this.partsel;
			},
			/** (experimental) Return true if this is partially loaded.
			 * @returns {boolean}
			 * @since 2.15
			 */
			isPartload: function () {
				return !!this.partload;
			},
			/** Return true if this is the (invisible) system root node.
			 * @returns {boolean}
			 * @since 2.4
			 */
			isRootNode: function () {
				return this.tree.rootNode === this;
			},
			/** Return true if node is selected, i.e. has a checkmark set (see also FancytreeNode#isActive).
			 * @returns {boolean}
			 */
			isSelected: function () {
				return !!this.selected;
			},
			/** Return true if this node is a temporarily generated system node like
			 * 'loading', 'paging', or 'error' (node.statusNodeType contains the type).
			 * @returns {boolean}
			 */
			isStatusNode: function () {
				return !!this.statusNodeType;
			},
			/** Return true if this node is a status node of type 'paging'.
			 * @returns {boolean}
			 * @since 2.15
			 */
			isPagingNode: function () {
				return this.statusNodeType === "paging";
			},
			/** Return true if this a top level node, i.e. a direct child of the (invisible) system root node.
			 * @returns {boolean}
			 * @since 2.4
			 */
			isTopLevel: function () {
				return this.tree.rootNode === this.parent;
			},
			/** Return true if node is lazy and not yet loaded. For non-lazy nodes always return false.
			 * @returns {boolean}
			 */
			isUndefined: function () {
				return this.hasChildren() === undefined; // also checks if the only child is a status node
			},
			/** Return true if all parent nodes are expanded. Note: this does not check
			 * whether the node is scrolled into the visible part of the screen.
			 * @returns {boolean}
			 */
			isVisible: function () {
				var i,
					l,
					n,
					hasFilter = this.tree.enableFilter,
					parents = this.getParentList(false, false);

				// TODO: check $(n.span).is(":visible")
				// i.e. return false for nodes (but not parents) that are hidden
				// by a filter
				if (hasFilter && !this.match && !this.subMatchCount) {
					// this.debug( "isVisible: HIDDEN (" + hasFilter + ", " + this.match + ", " + this.match + ")" );
					return false;
				}

				for (i = 0, l = parents.length; i < l; i++) {
					n = parents[i];

					if (!n.expanded) {
						// this.debug("isVisible: HIDDEN (parent collapsed)");
						return false;
					}
					// if (hasFilter && !n.match && !n.subMatchCount) {
					// 	this.debug("isVisible: HIDDEN (" + hasFilter + ", " + this.match + ", " + this.match + ")");
					// 	return false;
					// }
				}
				// this.debug("isVisible: VISIBLE");
				return true;
			},
			/** Deprecated.
			 * @deprecated since 2014-02-16: use load() instead.
			 */
			lazyLoad: function (discard) {
				$.error(
					"FancytreeNode.lazyLoad() is deprecated since 2014-02-16. Use .load() instead."
				);
			},
			/**
			 * Load all children of a lazy node if neccessary. The <i>expanded</i> state is maintained.
			 * @param {boolean} [forceReload=false] Pass true to discard any existing nodes before. Otherwise this method does nothing if the node was already loaded.
			 * @returns {$.Promise}
			 */
			load: function (forceReload) {
				var res,
					source,
					self = this,
					wasExpanded = this.isExpanded();

				_assert(this.isLazy(), "load() requires a lazy node");
				// _assert( forceReload || this.isUndefined(), "Pass forceReload=true to re-load a lazy node" );
				if (!forceReload && !this.isUndefined()) {
					return _getResolvedPromise(this);
				}
				if (this.isLoaded()) {
					this.resetLazy(); // also collapses
				}
				// This method is also called by setExpanded() and loadKeyPath(), so we
				// have to avoid recursion.
				source = this.tree._triggerNodeEvent("lazyLoad", this);
				if (source === false) {
					// #69
					return _getResolvedPromise(this);
				}
				_assert(
					typeof source !== "boolean",
					"lazyLoad event must return source in data.result"
				);
				res = this.tree._callHook("nodeLoadChildren", this, source);
				if (wasExpanded) {
					this.expanded = true;
					res.always(function () {
						self.render();
					});
				} else {
					res.always(function () {
						self.renderStatus(); // fix expander icon to 'loaded'
					});
				}
				return res;
			},
			/** Expand all parents and optionally scroll into visible area as neccessary.
			 * Promise is resolved, when lazy loading and animations are done.
			 * @param {object} [opts] passed to `setExpanded()`.
			 *     Defaults to {noAnimation: false, noEvents: false, scrollIntoView: true}
			 * @returns {$.Promise}
			 */
			makeVisible: function (opts) {
				var i,
					self = this,
					deferreds = [],
					dfd = new $.Deferred(),
					parents = this.getParentList(false, false),
					len = parents.length,
					effects = !(opts && opts.noAnimation === true),
					scroll = !(opts && opts.scrollIntoView === false);

				// Expand bottom-up, so only the top node is animated
				for (i = len - 1; i >= 0; i--) {
					// self.debug("pushexpand" + parents[i]);
					deferreds.push(parents[i].setExpanded(true, opts));
				}
				$.when.apply($, deferreds).done(function () {
					// All expands have finished
					// self.debug("expand DONE", scroll);
					if (scroll) {
						self.scrollIntoView(effects).done(function () {
							// self.debug("scroll DONE");
							dfd.resolve();
						});
					} else {
						dfd.resolve();
					}
				});
				return dfd.promise();
			},
			/** Move this node to targetNode.
			 *  @param {FancytreeNode} targetNode
			 *  @param {string} mode <pre>
			 *      'child': append this node as last child of targetNode.
			 *               This is the default. To be compatble with the D'n'd
			 *               hitMode, we also accept 'over'.
			 *      'firstChild': add this node as first child of targetNode.
			 *      'before': add this node as sibling before targetNode.
			 *      'after': add this node as sibling after targetNode.</pre>
			 *  @param {function} [map] optional callback(FancytreeNode) to allow modifcations
			 */
			moveTo: function (targetNode, mode, map) {
				if (mode === undefined || mode === "over") {
					mode = "child";
				} else if (mode === "firstChild") {
					if (targetNode.children && targetNode.children.length) {
						mode = "before";
						targetNode = targetNode.children[0];
					} else {
						mode = "child";
					}
				}
				var pos,
					tree = this.tree,
					prevParent = this.parent,
					targetParent =
						mode === "child" ? targetNode : targetNode.parent;

				if (this === targetNode) {
					return;
				} else if (!this.parent) {
					$.error("Cannot move system root");
				} else if (targetParent.isDescendantOf(this)) {
					$.error("Cannot move a node to its own descendant");
				}
				if (targetParent !== prevParent) {
					prevParent.triggerModifyChild("remove", this);
				}
				// Unlink this node from current parent
				if (this.parent.children.length === 1) {
					if (this.parent === targetParent) {
						return; // #258
					}
					this.parent.children = this.parent.lazy ? [] : null;
					this.parent.expanded = false;
				} else {
					pos = $.inArray(this, this.parent.children);
					_assert(pos >= 0, "invalid source parent");
					this.parent.children.splice(pos, 1);
				}
				// Remove from source DOM parent
				// if(this.parent.ul){
				// 	this.parent.ul.removeChild(this.li);
				// }

				// Insert this node to target parent's child list
				this.parent = targetParent;
				if (targetParent.hasChildren()) {
					switch (mode) {
						case "child":
							// Append to existing target children
							targetParent.children.push(this);
							break;
						case "before":
							// Insert this node before target node
							pos = $.inArray(targetNode, targetParent.children);
							_assert(pos >= 0, "invalid target parent");
							targetParent.children.splice(pos, 0, this);
							break;
						case "after":
							// Insert this node after target node
							pos = $.inArray(targetNode, targetParent.children);
							_assert(pos >= 0, "invalid target parent");
							targetParent.children.splice(pos + 1, 0, this);
							break;
						default:
							$.error("Invalid mode " + mode);
					}
				} else {
					targetParent.children = [this];
				}
				// Parent has no <ul> tag yet:
				// if( !targetParent.ul ) {
				// 	// This is the parent's first child: create UL tag
				// 	// (Hidden, because it will be
				// 	targetParent.ul = document.createElement("ul");
				// 	targetParent.ul.style.display = "none";
				// 	targetParent.li.appendChild(targetParent.ul);
				// }
				// // Issue 319: Add to target DOM parent (only if node was already rendered(expanded))
				// if(this.li){
				// 	targetParent.ul.appendChild(this.li);
				// }

				// Let caller modify the nodes
				if (map) {
					targetNode.visit(map, true);
				}
				if (targetParent === prevParent) {
					targetParent.triggerModifyChild("move", this);
				} else {
					// prevParent.triggerModifyChild("remove", this);
					targetParent.triggerModifyChild("add", this);
				}
				// Handle cross-tree moves
				if (tree !== targetNode.tree) {
					// Fix node.tree for all source nodes
					// 	_assert(false, "Cross-tree move is not yet implemented.");
					this.warn("Cross-tree moveTo is experimental!");
					this.visit(function (n) {
						// TODO: fix selection state and activation, ...
						n.tree = targetNode.tree;
					}, true);
				}

				// A collaposed node won't re-render children, so we have to remove it manually
				// if( !targetParent.expanded ){
				//   prevParent.ul.removeChild(this.li);
				// }
				tree._callHook("treeStructureChanged", tree, "moveTo");

				// Update HTML markup
				if (!prevParent.isDescendantOf(targetParent)) {
					prevParent.render();
				}
				if (
					!targetParent.isDescendantOf(prevParent) &&
					targetParent !== prevParent
				) {
					targetParent.render();
				}
				// TODO: fix selection state
				// TODO: fix active state

				/*
				var tree = this.tree;
				var opts = tree.options;
				var pers = tree.persistence;

				// Always expand, if it's below minExpandLevel
				// tree.logDebug ("%s._addChildNode(%o), l=%o", this, ftnode, ftnode.getLevel());
				if ( opts.minExpandLevel >= ftnode.getLevel() ) {
					// tree.logDebug ("Force expand for %o", ftnode);
					this.bExpanded = true;
				}

				// In multi-hier mode, update the parents selection state
				// DT issue #82: only if not initializing, because the children may not exist yet
				// if( !ftnode.data.isStatusNode() && opts.selectMode==3 && !isInitializing )
				// 	ftnode._fixSelectionState();

				// In multi-hier mode, update the parents selection state
				if( ftnode.bSelected && opts.selectMode==3 ) {
					var p = this;
					while( p ) {
						if( !p.hasSubSel )
							p._setSubSel(true);
						p = p.parent;
					}
				}
				// render this node and the new child
				if ( tree.bEnableUpdate )
					this.render();
				return ftnode;
				*/
			},
			/** Set focus relative to this node and optionally activate.
			 *
			 * 'left' collapses the node if it is expanded, or move to the parent
			 * otherwise.
			 * 'right' expands the node if it is collapsed, or move to the first
			 * child otherwise.
			 *
			 * @param {string|number} where 'down', 'first', 'last', 'left', 'parent', 'right', or 'up'.
			 *   (Alternatively the keyCode that would normally trigger this move,
			 *   e.g. `$.ui.keyCode.LEFT` = 'left'.
			 * @param {boolean} [activate=true]
			 * @returns {$.Promise}
			 */
			navigate: function (where, activate) {
				var node,
					KC = $.ui.keyCode;

				// Handle optional expand/collapse action for LEFT/RIGHT
				switch (where) {
					case "left":
					case KC.LEFT:
						if (this.expanded) {
							return this.setExpanded(false);
						}
						break;
					case "right":
					case KC.RIGHT:
						if (!this.expanded && (this.children || this.lazy)) {
							return this.setExpanded();
						}
						break;
				}
				// Otherwise activate or focus the related node
				node = this.findRelatedNode(where);
				if (node) {
					// setFocus/setActive will scroll later (if autoScroll is specified)
					try {
						node.makeVisible({ scrollIntoView: false });
					} catch (e) {} // #272
					if (activate === false) {
						node.setFocus();
						return _getResolvedPromise();
					}
					return node.setActive();
				}
				this.warn("Could not find related node '" + where + "'.");
				return _getResolvedPromise();
			},
			/**
			 * Remove this node (not allowed for system root).
			 */
			remove: function () {
				return this.parent.removeChild(this);
			},
			/**
			 * Remove childNode from list of direct children.
			 * @param {FancytreeNode} childNode
			 */
			removeChild: function (childNode) {
				return this.tree._callHook("nodeRemoveChild", this, childNode);
			},
			/**
			 * Remove all child nodes and descendents. This converts the node into a leaf.<br>
			 * If this was a lazy node, it is still considered 'loaded'; call node.resetLazy()
			 * in order to trigger lazyLoad on next expand.
			 */
			removeChildren: function () {
				return this.tree._callHook("nodeRemoveChildren", this);
			},
			/**
			 * Remove class from node's span tag and .extraClasses.
			 *
			 * @param {string} className class name
			 *
			 * @since 2.17
			 */
			removeClass: function (className) {
				return this.toggleClass(className, false);
			},
			/**
			 * This method renders and updates all HTML markup that is required
			 * to display this node in its current state.<br>
			 * Note:
			 * <ul>
			 * <li>It should only be neccessary to call this method after the node object
			 *     was modified by direct access to its properties, because the common
			 *     API methods (node.setTitle(), moveTo(), addChildren(), remove(), ...)
			 *     already handle this.
			 * <li> {@link FancytreeNode#renderTitle} and {@link FancytreeNode#renderStatus}
			 *     are implied. If changes are more local, calling only renderTitle() or
			 *     renderStatus() may be sufficient and faster.
			 * </ul>
			 *
			 * @param {boolean} [force=false] re-render, even if html markup was already created
			 * @param {boolean} [deep=false] also render all descendants, even if parent is collapsed
			 */
			render: function (force, deep) {
				return this.tree._callHook("nodeRender", this, force, deep);
			},
			/** Create HTML markup for the node's outer `<span>` (expander, checkbox, icon, and title).
			 * Implies {@link FancytreeNode#renderStatus}.
			 * @see Fancytree_Hooks#nodeRenderTitle
			 */
			renderTitle: function () {
				return this.tree._callHook("nodeRenderTitle", this);
			},
			/** Update element's CSS classes according to node state.
			 * @see Fancytree_Hooks#nodeRenderStatus
			 */
			renderStatus: function () {
				return this.tree._callHook("nodeRenderStatus", this);
			},
			/**
			 * (experimental) Replace this node with `source`.
			 * (Currently only available for paging nodes.)
			 * @param {NodeData[]} source List of child node definitions
			 * @since 2.15
			 */
			replaceWith: function (source) {
				var res,
					parent = this.parent,
					pos = $.inArray(this, parent.children),
					self = this;

				_assert(
					this.isPagingNode(),
					"replaceWith() currently requires a paging status node"
				);

				res = this.tree._callHook("nodeLoadChildren", this, source);
				res.done(function (data) {
					// New nodes are currently children of `this`.
					var children = self.children;
					// Prepend newly loaded child nodes to `this`
					// Move new children after self
					for (i = 0; i < children.length; i++) {
						children[i].parent = parent;
					}
					parent.children.splice.apply(
						parent.children,
						[pos + 1, 0].concat(children)
					);

					// Remove self
					self.children = null;
					self.remove();
					// Redraw new nodes
					parent.render();
					// TODO: set node.partload = false if this was tha last paging node?
					// parent.addPagingNode(false);
				}).fail(function () {
					self.setExpanded();
				});
				return res;
				// $.error("Not implemented: replaceWith()");
			},
			/**
			 * Remove all children, collapse, and set the lazy-flag, so that the lazyLoad
			 * event is triggered on next expand.
			 */
			resetLazy: function () {
				this.removeChildren();
				this.expanded = false;
				this.lazy = true;
				this.children = undefined;
				this.renderStatus();
			},
			/** Schedule activity for delayed execution (cancel any pending request).
			 *  scheduleAction('cancel') will only cancel a pending request (if any).
			 * @param {string} mode
			 * @param {number} ms
			 */
			scheduleAction: function (mode, ms) {
				if (this.tree.timer) {
					clearTimeout(this.tree.timer);
					this.tree.debug("clearTimeout(%o)", this.tree.timer);
				}
				this.tree.timer = null;
				var self = this; // required for closures
				switch (mode) {
					case "cancel":
						// Simply made sure that timer was cleared
						break;
					case "expand":
						this.tree.timer = setTimeout(function () {
							self.tree.debug("setTimeout: trigger expand");
							self.setExpanded(true);
						}, ms);
						break;
					case "activate":
						this.tree.timer = setTimeout(function () {
							self.tree.debug("setTimeout: trigger activate");
							self.setActive(true);
						}, ms);
						break;
					default:
						$.error("Invalid mode " + mode);
				}
				// this.tree.debug("setTimeout(%s, %s): %s", mode, ms, this.tree.timer);
			},
			/**
			 *
			 * @param {boolean | PlainObject} [effects=false] animation options.
			 * @param {object} [options=null] {topNode: null, effects: ..., parent: ...} this node will remain visible in
			 *     any case, even if `this` is outside the scroll pane.
			 * @returns {$.Promise}
			 */
			scrollIntoView: function (effects, options) {
				if (options !== undefined && _isNode(options)) {
					throw Error(
						"scrollIntoView() with 'topNode' option is deprecated since 2014-05-08. Use 'options.topNode' instead."
					);
				}
				// The scroll parent is typically the plain tree's <UL> container.
				// For ext-table, we choose the nearest parent that has `position: relative`
				// and `overflow` set.
				// (This default can be overridden by the local or global `scrollParent` option.)
				var opts = $.extend(
						{
							effects:
								effects === true
									? { duration: 200, queue: false }
									: effects,
							scrollOfs: this.tree.options.scrollOfs,
							scrollParent: this.tree.options.scrollParent,
							topNode: null,
						},
						options
					),
					$scrollParent = opts.scrollParent,
					$container = this.tree.$container,
					overflowY = $container.css("overflow-y");

				if (!$scrollParent) {
					if (this.tree.tbody) {
						$scrollParent = $container.scrollParent();
					} else if (overflowY === "scroll" || overflowY === "auto") {
						$scrollParent = $container;
					} else {
						// #922 plain tree in a non-fixed-sized UL scrolls inside its parent
						$scrollParent = $container.scrollParent();
					}
				} else if (!$scrollParent.jquery) {
					// Make sure we have a jQuery object
					$scrollParent = $($scrollParent);
				}
				if (
					$scrollParent[0] === document ||
					$scrollParent[0] === document.body
				) {
					// `document` may be returned by $().scrollParent(), if nothing is found,
					// but would not work: (see #894)
					this.debug(
						"scrollIntoView(): normalizing scrollParent to 'window':",
						$scrollParent[0]
					);
					$scrollParent = $(window);
				}
				// eslint-disable-next-line one-var
				var topNodeY,
					nodeY,
					horzScrollbarHeight,
					containerOffsetTop,
					dfd = new $.Deferred(),
					self = this,
					nodeHeight = $(this.span).height(),
					topOfs = opts.scrollOfs.top || 0,
					bottomOfs = opts.scrollOfs.bottom || 0,
					containerHeight = $scrollParent.height(),
					scrollTop = $scrollParent.scrollTop(),
					$animateTarget = $scrollParent,
					isParentWindow = $scrollParent[0] === window,
					topNode = opts.topNode || null,
					newScrollTop = null;

				// this.debug("scrollIntoView(), scrollTop=" + scrollTop, opts.scrollOfs);
				// _assert($(this.span).is(":visible"), "scrollIntoView node is invisible"); // otherwise we cannot calc offsets
				if (this.isRootNode() || !this.isVisible()) {
					// We cannot calc offsets for hidden elements
					this.info("scrollIntoView(): node is invisible.");
					return _getResolvedPromise();
				}
				if (isParentWindow) {
					nodeY = $(this.span).offset().top;
					topNodeY =
						topNode && topNode.span ? $(topNode.span).offset().top : 0;
					$animateTarget = $("html,body");
				} else {
					_assert(
						$scrollParent[0] !== document &&
							$scrollParent[0] !== document.body,
						"scrollParent should be a simple element or `window`, not document or body."
					);

					containerOffsetTop = $scrollParent.offset().top;
					nodeY =
						$(this.span).offset().top - containerOffsetTop + scrollTop; // relative to scroll parent
					topNodeY = topNode
						? $(topNode.span).offset().top -
						  containerOffsetTop +
						  scrollTop
						: 0;
					horzScrollbarHeight = Math.max(
						0,
						$scrollParent.innerHeight() - $scrollParent[0].clientHeight
					);
					containerHeight -= horzScrollbarHeight;
				}

				// this.debug("    scrollIntoView(), nodeY=" + nodeY + ", containerHeight=" + containerHeight);
				if (nodeY < scrollTop + topOfs) {
					// Node is above visible container area
					newScrollTop = nodeY - topOfs;
					// this.debug("    scrollIntoView(), UPPER newScrollTop=" + newScrollTop);
				} else if (
					nodeY + nodeHeight >
					scrollTop + containerHeight - bottomOfs
				) {
					newScrollTop = nodeY + nodeHeight - containerHeight + bottomOfs;
					// this.debug("    scrollIntoView(), LOWER newScrollTop=" + newScrollTop);
					// If a topNode was passed, make sure that it is never scrolled
					// outside the upper border
					if (topNode) {
						_assert(
							topNode.isRootNode() || topNode.isVisible(),
							"topNode must be visible"
						);
						if (topNodeY < newScrollTop) {
							newScrollTop = topNodeY - topOfs;
							// this.debug("    scrollIntoView(), TOP newScrollTop=" + newScrollTop);
						}
					}
				}

				if (newScrollTop === null) {
					dfd.resolveWith(this);
				} else {
					// this.debug("    scrollIntoView(), SET newScrollTop=" + newScrollTop);
					if (opts.effects) {
						opts.effects.complete = function () {
							dfd.resolveWith(self);
						};
						$animateTarget.stop(true).animate(
							{
								scrollTop: newScrollTop,
							},
							opts.effects
						);
					} else {
						$animateTarget[0].scrollTop = newScrollTop;
						dfd.resolveWith(this);
					}
				}
				return dfd.promise();
			},

			/**Activate this node.
			 *
			 * The `cell` option requires the ext-table and ext-ariagrid extensions.
			 *
			 * @param {boolean} [flag=true] pass false to deactivate
			 * @param {object} [opts] additional options. Defaults to {noEvents: false, noFocus: false, cell: null}
			 * @returns {$.Promise}
			 */
			setActive: function (flag, opts) {
				return this.tree._callHook("nodeSetActive", this, flag, opts);
			},
			/**Expand or collapse this node. Promise is resolved, when lazy loading and animations are done.
			 * @param {boolean} [flag=true] pass false to collapse
			 * @param {object} [opts] additional options. Defaults to {noAnimation: false, noEvents: false}
			 * @returns {$.Promise}
			 */
			setExpanded: function (flag, opts) {
				return this.tree._callHook("nodeSetExpanded", this, flag, opts);
			},
			/**Set keyboard focus to this node.
			 * @param {boolean} [flag=true] pass false to blur
			 * @see Fancytree#setFocus
			 */
			setFocus: function (flag) {
				return this.tree._callHook("nodeSetFocus", this, flag);
			},
			/**Select this node, i.e. check the checkbox.
			 * @param {boolean} [flag=true] pass false to deselect
			 * @param {object} [opts] additional options. Defaults to {noEvents: false, p
			 *     propagateDown: null, propagateUp: null, callback: null }
			 */
			setSelected: function (flag, opts) {
				return this.tree._callHook("nodeSetSelected", this, flag, opts);
			},
			/**Mark a lazy node as 'error', 'loading', 'nodata', or 'ok'.
			 * @param {string} status 'error'|'loading'|'nodata'|'ok'
			 * @param {string} [message]
			 * @param {string} [details]
			 */
			setStatus: function (status, message, details) {
				return this.tree._callHook(
					"nodeSetStatus",
					this,
					status,
					message,
					details
				);
			},
			/**Rename this node.
			 * @param {string} title
			 */
			setTitle: function (title) {
				this.title = title;
				this.renderTitle();
				this.triggerModify("rename");
			},
			/**Sort child list by title.
			 * @param {function} [cmp] custom compare function(a, b) that returns -1, 0, or 1 (defaults to sort by title).
			 * @param {boolean} [deep=false] pass true to sort all descendant nodes
			 */
			sortChildren: function (cmp, deep) {
				var i,
					l,
					cl = this.children;

				if (!cl) {
					return;
				}
				cmp =
					cmp ||
					function (a, b) {
						var x = a.title.toLowerCase(),
							y = b.title.toLowerCase();

						// eslint-disable-next-line no-nested-ternary
						return x === y ? 0 : x > y ? 1 : -1;
					};
				cl.sort(cmp);
				if (deep) {
					for (i = 0, l = cl.length; i < l; i++) {
						if (cl[i].children) {
							cl[i].sortChildren(cmp, "$norender$");
						}
					}
				}
				if (deep !== "$norender$") {
					this.render();
				}
				this.triggerModifyChild("sort");
			},
			/** Convert node (or whole branch) into a plain object.
			 *
			 * The result is compatible with node.addChildren().
			 *
			 * @param {boolean} [recursive=false] include child nodes
			 * @param {function} [callback] callback(dict, node) is called for every node, in order to allow modifications.
			 *     Return `false` to ignore this node or `"skip"` to include this node without its children.
			 * @returns {NodeData}
			 */
			toDict: function (recursive, callback) {
				var i,
					l,
					node,
					res,
					dict = {},
					self = this;

				$.each(NODE_ATTRS, function (i, a) {
					if (self[a] || self[a] === false) {
						dict[a] = self[a];
					}
				});
				if (!$.isEmptyObject(this.data)) {
					dict.data = $.extend({}, this.data);
					if ($.isEmptyObject(dict.data)) {
						delete dict.data;
					}
				}
				if (callback) {
					res = callback(dict, self);
					if (res === false) {
						return false; // Don't include this node nor its children
					}
					if (res === "skip") {
						recursive = false; // Include this node, but not the children
					}
				}
				if (recursive) {
					if (_isArray(this.children)) {
						dict.children = [];
						for (i = 0, l = this.children.length; i < l; i++) {
							node = this.children[i];
							if (!node.isStatusNode()) {
								res = node.toDict(true, callback);
								if (res !== false) {
									dict.children.push(res);
								}
							}
						}
					}
				}
				return dict;
			},
			/**
			 * Set, clear, or toggle class of node's span tag and .extraClasses.
			 *
			 * @param {string} className class name (separate multiple classes by space)
			 * @param {boolean} [flag] true/false to add/remove class. If omitted, class is toggled.
			 * @returns {boolean} true if a class was added
			 *
			 * @since 2.17
			 */
			toggleClass: function (value, flag) {
				var className,
					hasClass,
					rnotwhite = /\S+/g,
					classNames = value.match(rnotwhite) || [],
					i = 0,
					wasAdded = false,
					statusElem = this[this.tree.statusClassPropName],
					curClasses = " " + (this.extraClasses || "") + " ";

				// this.info("toggleClass('" + value + "', " + flag + ")", curClasses);
				// Modify DOM element directly if it already exists
				if (statusElem) {
					$(statusElem).toggleClass(value, flag);
				}
				// Modify node.extraClasses to make this change persistent
				// Toggle if flag was not passed
				while ((className = classNames[i++])) {
					hasClass = curClasses.indexOf(" " + className + " ") >= 0;
					flag = flag === undefined ? !hasClass : !!flag;
					if (flag) {
						if (!hasClass) {
							curClasses += className + " ";
							wasAdded = true;
						}
					} else {
						while (curClasses.indexOf(" " + className + " ") > -1) {
							curClasses = curClasses.replace(
								" " + className + " ",
								" "
							);
						}
					}
				}
				this.extraClasses = _trim(curClasses);
				// this.info("-> toggleClass('" + value + "', " + flag + "): '" + this.extraClasses + "'");
				return wasAdded;
			},
			/** Flip expanded status. */
			toggleExpanded: function () {
				return this.tree._callHook("nodeToggleExpanded", this);
			},
			/** Flip selection status. */
			toggleSelected: function () {
				return this.tree._callHook("nodeToggleSelected", this);
			},
			toString: function () {
				return "FancytreeNode@" + this.key + "[title='" + this.title + "']";
				// return "<FancytreeNode(#" + this.key + ", '" + this.title + "')>";
			},
			/**
			 * Trigger `modifyChild` event on a parent to signal that a child was modified.
			 * @param {string} operation Type of change: 'add', 'remove', 'rename', 'move', 'data', ...
			 * @param {FancytreeNode} [childNode]
			 * @param {object} [extra]
			 */
			triggerModifyChild: function (operation, childNode, extra) {
				var data,
					modifyChild = this.tree.options.modifyChild;

				if (modifyChild) {
					if (childNode && childNode.parent !== this) {
						$.error(
							"childNode " + childNode + " is not a child of " + this
						);
					}
					data = {
						node: this,
						tree: this.tree,
						operation: operation,
						childNode: childNode || null,
					};
					if (extra) {
						$.extend(data, extra);
					}
					modifyChild({ type: "modifyChild" }, data);
				}
			},
			/**
			 * Trigger `modifyChild` event on node.parent(!).
			 * @param {string} operation Type of change: 'add', 'remove', 'rename', 'move', 'data', ...
			 * @param {object} [extra]
			 */
			triggerModify: function (operation, extra) {
				this.parent.triggerModifyChild(operation, this, extra);
			},
			/** Call fn(node) for all child nodes in hierarchical order (depth-first).<br>
			 * Stop iteration, if fn() returns false. Skip current branch, if fn() returns "skip".<br>
			 * Return false if iteration was stopped.
			 *
			 * @param {function} fn the callback function.
			 *     Return false to stop iteration, return "skip" to skip this node and
			 *     its children only.
			 * @param {boolean} [includeSelf=false]
			 * @returns {boolean}
			 */
			visit: function (fn, includeSelf) {
				var i,
					l,
					res = true,
					children = this.children;

				if (includeSelf === true) {
					res = fn(this);
					if (res === false || res === "skip") {
						return res;
					}
				}
				if (children) {
					for (i = 0, l = children.length; i < l; i++) {
						res = children[i].visit(fn, true);
						if (res === false) {
							break;
						}
					}
				}
				return res;
			},
			/** Call fn(node) for all child nodes and recursively load lazy children.<br>
			 * <b>Note:</b> If you need this method, you probably should consider to review
			 * your architecture! Recursivley loading nodes is a perfect way for lazy
			 * programmers to flood the server with requests ;-)
			 *
			 * @param {function} [fn] optional callback function.
			 *     Return false to stop iteration, return "skip" to skip this node and
			 *     its children only.
			 * @param {boolean} [includeSelf=false]
			 * @returns {$.Promise}
			 * @since 2.4
			 */
			visitAndLoad: function (fn, includeSelf, _recursion) {
				var dfd,
					res,
					loaders,
					node = this;

				// node.debug("visitAndLoad");
				if (fn && includeSelf === true) {
					res = fn(node);
					if (res === false || res === "skip") {
						return _recursion ? res : _getResolvedPromise();
					}
				}
				if (!node.children && !node.lazy) {
					return _getResolvedPromise();
				}
				dfd = new $.Deferred();
				loaders = [];
				// node.debug("load()...");
				node.load().done(function () {
					// node.debug("load()... done.");
					for (var i = 0, l = node.children.length; i < l; i++) {
						res = node.children[i].visitAndLoad(fn, true, true);
						if (res === false) {
							dfd.reject();
							break;
						} else if (res !== "skip") {
							loaders.push(res); // Add promise to the list
						}
					}
					$.when.apply(this, loaders).then(function () {
						dfd.resolve();
					});
				});
				return dfd.promise();
			},
			/** Call fn(node) for all parent nodes, bottom-up, including invisible system root.<br>
			 * Stop iteration, if fn() returns false.<br>
			 * Return false if iteration was stopped.
			 *
			 * @param {function} fn the callback function.
			 *     Return false to stop iteration, return "skip" to skip this node and children only.
			 * @param {boolean} [includeSelf=false]
			 * @returns {boolean}
			 */
			visitParents: function (fn, includeSelf) {
				// Visit parent nodes (bottom up)
				if (includeSelf && fn(this) === false) {
					return false;
				}
				var p = this.parent;
				while (p) {
					if (fn(p) === false) {
						return false;
					}
					p = p.parent;
				}
				return true;
			},
			/** Call fn(node) for all sibling nodes.<br>
			 * Stop iteration, if fn() returns false.<br>
			 * Return false if iteration was stopped.
			 *
			 * @param {function} fn the callback function.
			 *     Return false to stop iteration.
			 * @param {boolean} [includeSelf=false]
			 * @returns {boolean}
			 */
			visitSiblings: function (fn, includeSelf) {
				var i,
					l,
					n,
					ac = this.parent.children;

				for (i = 0, l = ac.length; i < l; i++) {
					n = ac[i];
					if (includeSelf || n !== this) {
						if (fn(n) === false) {
							return false;
						}
					}
				}
				return true;
			},
			/** Write warning to browser console if debugLevel >= 2 (prepending node info)
			 *
			 * @param {*} msg string or object or array of such
			 */
			warn: function (msg) {
				if (this.tree.options.debugLevel >= 2) {
					Array.prototype.unshift.call(arguments, this.toString());
					consoleApply("warn", arguments);
				}
			},
		};

		/******************************************************************************
		 * Fancytree
		 */
		/**
		 * Construct a new tree object.
		 *
		 * @class Fancytree
		 * @classdesc The controller behind a fancytree.
		 * This class also contains 'hook methods': see {@link Fancytree_Hooks}.
		 *
		 * @param {Widget} widget
		 *
		 * @property {string} _id Automatically generated unique tree instance ID, e.g. "1".
		 * @property {string} _ns Automatically generated unique tree namespace, e.g. ".fancytree-1".
		 * @property {FancytreeNode} activeNode Currently active node or null.
		 * @property {string} ariaPropName Property name of FancytreeNode that contains the element which will receive the aria attributes.
		 *     Typically "li", but "tr" for table extension.
		 * @property {jQueryObject} $container Outer `<ul>` element (or `<table>` element for ext-table).
		 * @property {jQueryObject} $div A jQuery object containing the element used to instantiate the tree widget (`widget.element`)
		 * @property {object|array} columns Recommended place to store shared column meta data. @since 2.27
		 * @property {object} data Metadata, i.e. properties that may be passed to `source` in addition to a children array.
		 * @property {object} ext Hash of all active plugin instances.
		 * @property {FancytreeNode} focusNode Currently focused node or null.
		 * @property {FancytreeNode} lastSelectedNode Used to implement selectMode 1 (single select)
		 * @property {string} nodeContainerAttrName Property name of FancytreeNode that contains the outer element of single nodes.
		 *     Typically "li", but "tr" for table extension.
		 * @property {FancytreeOptions} options Current options, i.e. default options + options passed to constructor.
		 * @property {FancytreeNode} rootNode Invisible system root node.
		 * @property {string} statusClassPropName Property name of FancytreeNode that contains the element which will receive the status classes.
		 *     Typically "span", but "tr" for table extension.
		 * @property {object} types Map for shared type specific meta data, used with node.type attribute. @since 2.27
		 * @property {object} viewport See ext-vieport. @since v2.31
		 * @property {object} widget Base widget instance.
		 */
		function Fancytree(widget) {
			this.widget = widget;
			this.$div = widget.element;
			this.options = widget.options;
			if (this.options) {
				if (this.options.lazyload !== undefined) {
					$.error(
						"The 'lazyload' event is deprecated since 2014-02-25. Use 'lazyLoad' (with uppercase L) instead."
					);
				}
				if (this.options.loaderror !== undefined) {
					$.error(
						"The 'loaderror' event was renamed since 2014-07-03. Use 'loadError' (with uppercase E) instead."
					);
				}
				if (this.options.fx !== undefined) {
					$.error(
						"The 'fx' option was replaced by 'toggleEffect' since 2014-11-30."
					);
				}
				if (this.options.removeNode !== undefined) {
					$.error(
						"The 'removeNode' event was replaced by 'modifyChild' since 2.20 (2016-09-10)."
					);
				}
			}
			this.ext = {}; // Active extension instances
			this.types = {};
			this.columns = {};
			// allow to init tree.data.foo from <div data-foo=''>
			this.data = _getElementDataAsDict(this.$div);
			// TODO: use widget.uuid instead?
			this._id = "" + (this.options.treeId || $.ui.fancytree._nextId++);
			// TODO: use widget.eventNamespace instead?
			this._ns = ".fancytree-" + this._id; // append for namespaced events
			this.activeNode = null;
			this.focusNode = null;
			this._hasFocus = null;
			this._tempCache = {};
			this._lastMousedownNode = null;
			this._enableUpdate = true;
			this.lastSelectedNode = null;
			this.systemFocusElement = null;
			this.lastQuicksearchTerm = "";
			this.lastQuicksearchTime = 0;
			this.viewport = null; // ext-grid

			this.statusClassPropName = "span";
			this.ariaPropName = "li";
			this.nodeContainerAttrName = "li";

			// Remove previous markup if any
			this.$div.find(">ul.fancytree-container").remove();

			// Create a node without parent.
			var fakeParent = { tree: this },
				$ul;
			this.rootNode = new FancytreeNode(fakeParent, {
				title: "root",
				key: "root_" + this._id,
				children: null,
				expanded: true,
			});
			this.rootNode.parent = null;

			// Create root markup
			$ul = $("<ul>", {
				id: "ft-id-" + this._id,
				class: "ui-fancytree fancytree-container fancytree-plain",
			}).appendTo(this.$div);
			this.$container = $ul;
			this.rootNode.ul = $ul[0];

			if (this.options.debugLevel == null) {
				this.options.debugLevel = FT.debugLevel;
			}
			// // Add container to the TAB chain
			// // See http://www.w3.org/TR/wai-aria-practices/#focus_activedescendant
			// // #577: Allow to set tabindex to "0", "-1" and ""
			// this.$container.attr("tabindex", this.options.tabindex);

			// if( this.options.rtl ) {
			// 	this.$container.attr("DIR", "RTL").addClass("fancytree-rtl");
			// // }else{
			// //	this.$container.attr("DIR", null).removeClass("fancytree-rtl");
			// }
			// if(this.options.aria){
			// 	this.$container.attr("role", "tree");
			// 	if( this.options.selectMode !== 1 ) {
			// 		this.$container.attr("aria-multiselectable", true);
			// 	}
			// }
		}

		Fancytree.prototype = /** @lends Fancytree# */ {
			/* Return a context object that can be re-used for _callHook().
			 * @param {Fancytree | FancytreeNode | EventData} obj
			 * @param {Event} originalEvent
			 * @param {Object} extra
			 * @returns {EventData}
			 */
			_makeHookContext: function (obj, originalEvent, extra) {
				var ctx, tree;
				if (obj.node !== undefined) {
					// obj is already a context object
					if (originalEvent && obj.originalEvent !== originalEvent) {
						$.error("invalid args");
					}
					ctx = obj;
				} else if (obj.tree) {
					// obj is a FancytreeNode
					tree = obj.tree;
					ctx = {
						node: obj,
						tree: tree,
						widget: tree.widget,
						options: tree.widget.options,
						originalEvent: originalEvent,
						typeInfo: tree.types[obj.type] || {},
					};
				} else if (obj.widget) {
					// obj is a Fancytree
					ctx = {
						node: null,
						tree: obj,
						widget: obj.widget,
						options: obj.widget.options,
						originalEvent: originalEvent,
					};
				} else {
					$.error("invalid args");
				}
				if (extra) {
					$.extend(ctx, extra);
				}
				return ctx;
			},
			/* Trigger a hook function: funcName(ctx, [...]).
			 *
			 * @param {string} funcName
			 * @param {Fancytree|FancytreeNode|EventData} contextObject
			 * @param {any}  [_extraArgs] optional additional arguments
			 * @returns {any}
			 */
			_callHook: function (funcName, contextObject, _extraArgs) {
				var ctx = this._makeHookContext(contextObject),
					fn = this[funcName],
					args = Array.prototype.slice.call(arguments, 2);
				if (!_isFunction(fn)) {
					$.error("_callHook('" + funcName + "') is not a function");
				}
				args.unshift(ctx);
				// this.debug("_hook", funcName, ctx.node && ctx.node.toString() || ctx.tree.toString(), args);
				return fn.apply(this, args);
			},
			_setExpiringValue: function (key, value, ms) {
				this._tempCache[key] = {
					value: value,
					expire: Date.now() + (+ms || 50),
				};
			},
			_getExpiringValue: function (key) {
				var entry = this._tempCache[key];
				if (entry && entry.expire > Date.now()) {
					return entry.value;
				}
				delete this._tempCache[key];
				return null;
			},
			/* Check if this tree has extension `name` enabled.
			 *
			 * @param {string} name name of the required extension
			 */
			_usesExtension: function (name) {
				return $.inArray(name, this.options.extensions) >= 0;
			},
			/* Check if current extensions dependencies are met and throw an error if not.
			 *
			 * This method may be called inside the `treeInit` hook for custom extensions.
			 *
			 * @param {string} name name of the required extension
			 * @param {boolean} [required=true] pass `false` if the extension is optional, but we want to check for order if it is present
			 * @param {boolean} [before] `true` if `name` must be included before this, `false` otherwise (use `null` if order doesn't matter)
			 * @param {string} [message] optional error message (defaults to a descriptve error message)
			 */
			_requireExtension: function (name, required, before, message) {
				if (before != null) {
					before = !!before;
				}
				var thisName = this._local.name,
					extList = this.options.extensions,
					isBefore =
						$.inArray(name, extList) < $.inArray(thisName, extList),
					isMissing = required && this.ext[name] == null,
					badOrder = !isMissing && before != null && before !== isBefore;

				_assert(
					thisName && thisName !== name,
					"invalid or same name '" + thisName + "' (require yourself?)"
				);

				if (isMissing || badOrder) {
					if (!message) {
						if (isMissing || required) {
							message =
								"'" +
								thisName +
								"' extension requires '" +
								name +
								"'";
							if (badOrder) {
								message +=
									" to be registered " +
									(before ? "before" : "after") +
									" itself";
							}
						} else {
							message =
								"If used together, `" +
								name +
								"` must be registered " +
								(before ? "before" : "after") +
								" `" +
								thisName +
								"`";
						}
					}
					$.error(message);
					return false;
				}
				return true;
			},
			/** Activate node with a given key and fire focus and activate events.
			 *
			 * A previously activated node will be deactivated.
			 * If activeVisible option is set, all parents will be expanded as necessary.
			 * Pass key = false, to deactivate the current node only.
			 * @param {string} key
			 * @param {object} [opts] additional options. Defaults to {noEvents: false, noFocus: false}
			 * @returns {FancytreeNode} activated node (null, if not found)
			 */
			activateKey: function (key, opts) {
				var node = this.getNodeByKey(key);
				if (node) {
					node.setActive(true, opts);
				} else if (this.activeNode) {
					this.activeNode.setActive(false, opts);
				}
				return node;
			},
			/** (experimental) Add child status nodes that indicate 'More...', ....
			 * @param {boolean|object} node optional node definition. Pass `false` to remove all paging nodes.
			 * @param {string} [mode='append'] 'child'|firstChild'
			 * @since 2.15
			 */
			addPagingNode: function (node, mode) {
				return this.rootNode.addPagingNode(node, mode);
			},
			/**
			 * (experimental) Apply a modification (or navigation) operation.
			 *
			 * Valid commands:
			 *   - 'moveUp', 'moveDown'
			 *   - 'indent', 'outdent'
			 *   - 'remove'
			 *   - 'edit', 'addChild', 'addSibling': (reqires ext-edit extension)
			 *   - 'cut', 'copy', 'paste': (use an internal singleton 'clipboard')
			 *   - 'down', 'first', 'last', 'left', 'parent', 'right', 'up': navigate
			 *
			 * @param {string} cmd
			 * @param {FancytreeNode} [node=active_node]
			 * @param {object} [opts] Currently unused
			 *
			 * @since 2.32
			 */
			applyCommand: function (cmd, node, opts_) {
				var // clipboard,
					refNode;
				// opts = $.extend(
				// 	{ setActive: true, clipboard: CLIPBOARD },
				// 	opts_
				// );

				node = node || this.getActiveNode();
				// clipboard = opts.clipboard;

				switch (cmd) {
					// Sorting and indentation:
					case "moveUp":
						refNode = node.getPrevSibling();
						if (refNode) {
							node.moveTo(refNode, "before");
							node.setActive();
						}
						break;
					case "moveDown":
						refNode = node.getNextSibling();
						if (refNode) {
							node.moveTo(refNode, "after");
							node.setActive();
						}
						break;
					case "indent":
						refNode = node.getPrevSibling();
						if (refNode) {
							node.moveTo(refNode, "child");
							refNode.setExpanded();
							node.setActive();
						}
						break;
					case "outdent":
						if (!node.isTopLevel()) {
							node.moveTo(node.getParent(), "after");
							node.setActive();
						}
						break;
					// Remove:
					case "remove":
						refNode = node.getPrevSibling() || node.getParent();
						node.remove();
						if (refNode) {
							refNode.setActive();
						}
						break;
					// Add, edit (requires ext-edit):
					case "addChild":
						node.editCreateNode("child", "");
						break;
					case "addSibling":
						node.editCreateNode("after", "");
						break;
					case "rename":
						node.editStart();
						break;
					// Simple clipboard simulation:
					// case "cut":
					// 	clipboard = { mode: cmd, data: node };
					// 	break;
					// case "copy":
					// 	clipboard = {
					// 		mode: cmd,
					// 		data: node.toDict(function(d, n) {
					// 			delete d.key;
					// 		}),
					// 	};
					// 	break;
					// case "clear":
					// 	clipboard = null;
					// 	break;
					// case "paste":
					// 	if (clipboard.mode === "cut") {
					// 		// refNode = node.getPrevSibling();
					// 		clipboard.data.moveTo(node, "child");
					// 		clipboard.data.setActive();
					// 	} else if (clipboard.mode === "copy") {
					// 		node.addChildren(clipboard.data).setActive();
					// 	}
					// 	break;
					// Navigation commands:
					case "down":
					case "first":
					case "last":
					case "left":
					case "parent":
					case "right":
					case "up":
						return node.navigate(cmd);
					default:
						$.error("Unhandled command: '" + cmd + "'");
				}
			},
			/** (experimental) Modify existing data model.
			 *
			 * @param {Array} patchList array of [key, NodePatch] arrays
			 * @returns {$.Promise} resolved, when all patches have been applied
			 * @see TreePatch
			 */
			applyPatch: function (patchList) {
				var dfd,
					i,
					p2,
					key,
					patch,
					node,
					patchCount = patchList.length,
					deferredList = [];

				for (i = 0; i < patchCount; i++) {
					p2 = patchList[i];
					_assert(
						p2.length === 2,
						"patchList must be an array of length-2-arrays"
					);
					key = p2[0];
					patch = p2[1];
					node = key === null ? this.rootNode : this.getNodeByKey(key);
					if (node) {
						dfd = new $.Deferred();
						deferredList.push(dfd);
						node.applyPatch(patch).always(_makeResolveFunc(dfd, node));
					} else {
						this.warn("could not find node with key '" + key + "'");
					}
				}
				// Return a promise that is resolved, when ALL patches were applied
				return $.when.apply($, deferredList).promise();
			},
			/* TODO: implement in dnd extension
			cancelDrag: function() {
					var dd = $.ui.ddmanager.current;
					if(dd){
						dd.cancel();
					}
				},
			*/
			/** Remove all nodes.
			 * @since 2.14
			 */
			clear: function (source) {
				this._callHook("treeClear", this);
			},
			/** Return the number of nodes.
			 * @returns {integer}
			 */
			count: function () {
				return this.rootNode.countChildren();
			},
			/** Write to browser console if debugLevel >= 4 (prepending tree name)
			 *
			 * @param {*} msg string or object or array of such
			 */
			debug: function (msg) {
				if (this.options.debugLevel >= 4) {
					Array.prototype.unshift.call(arguments, this.toString());
					consoleApply("log", arguments);
				}
			},
			/** Destroy this widget, restore previous markup and cleanup resources.
			 *
			 * @since 2.34
			 */
			destroy: function () {
				this.widget.destroy();
			},
			/** Enable (or disable) the tree control.
			 *
			 * @param {boolean} [flag=true] pass false to disable
			 * @since 2.30
			 */
			enable: function (flag) {
				if (flag === false) {
					this.widget.disable();
				} else {
					this.widget.enable();
				}
			},
			/** Temporarily suppress rendering to improve performance on bulk-updates.
			 *
			 * @param {boolean} flag
			 * @returns {boolean} previous status
			 * @since 2.19
			 */
			enableUpdate: function (flag) {
				flag = flag !== false;
				if (!!this._enableUpdate === !!flag) {
					return flag;
				}
				this._enableUpdate = flag;
				if (flag) {
					this.debug("enableUpdate(true): redraw "); //, this._dirtyRoots);
					this._callHook("treeStructureChanged", this, "enableUpdate");
					this.render();
				} else {
					// 	this._dirtyRoots = null;
					this.debug("enableUpdate(false)...");
				}
				return !flag; // return previous value
			},
			/** Write error to browser console if debugLevel >= 1 (prepending tree info)
			 *
			 * @param {*} msg string or object or array of such
			 */
			error: function (msg) {
				if (this.options.debugLevel >= 1) {
					Array.prototype.unshift.call(arguments, this.toString());
					consoleApply("error", arguments);
				}
			},
			/** Expand (or collapse) all parent nodes.
			 *
			 * This convenience method uses `tree.visit()` and `tree.setExpanded()`
			 * internally.
			 *
			 * @param {boolean} [flag=true] pass false to collapse
			 * @param {object} [opts] passed to setExpanded()
			 * @since 2.30
			 */
			expandAll: function (flag, opts) {
				var prev = this.enableUpdate(false);

				flag = flag !== false;
				this.visit(function (node) {
					if (
						node.hasChildren() !== false &&
						node.isExpanded() !== flag
					) {
						node.setExpanded(flag, opts);
					}
				});
				this.enableUpdate(prev);
			},
			/**Find all nodes that matches condition.
			 *
			 * @param {string | function(node)} match title string to search for, or a
			 *     callback function that returns `true` if a node is matched.
			 * @returns {FancytreeNode[]} array of nodes (may be empty)
			 * @see FancytreeNode#findAll
			 * @since 2.12
			 */
			findAll: function (match) {
				return this.rootNode.findAll(match);
			},
			/**Find first node that matches condition.
			 *
			 * @param {string | function(node)} match title string to search for, or a
			 *     callback function that returns `true` if a node is matched.
			 * @returns {FancytreeNode} matching node or null
			 * @see FancytreeNode#findFirst
			 * @since 2.12
			 */
			findFirst: function (match) {
				return this.rootNode.findFirst(match);
			},
			/** Find the next visible node that starts with `match`, starting at `startNode`
			 * and wrap-around at the end.
			 *
			 * @param {string|function} match
			 * @param {FancytreeNode} [startNode] defaults to first node
			 * @returns {FancytreeNode} matching node or null
			 */
			findNextNode: function (match, startNode) {
				//, visibleOnly) {
				var res = null,
					firstNode = this.getFirstChild();

				match =
					typeof match === "string"
						? _makeNodeTitleStartMatcher(match)
						: match;
				startNode = startNode || firstNode;

				function _checkNode(n) {
					// console.log("_check " + n)
					if (match(n)) {
						res = n;
					}
					if (res || n === startNode) {
						return false;
					}
				}
				this.visitRows(_checkNode, {
					start: startNode,
					includeSelf: false,
				});
				// Wrap around search
				if (!res && startNode !== firstNode) {
					this.visitRows(_checkNode, {
						start: firstNode,
						includeSelf: true,
					});
				}
				return res;
			},
			/** Find a node relative to another node.
			 *
			 * @param {FancytreeNode} node
			 * @param {string|number} where 'down', 'first', 'last', 'left', 'parent', 'right', or 'up'.
			 *   (Alternatively the keyCode that would normally trigger this move,
			 *   e.g. `$.ui.keyCode.LEFT` = 'left'.
			 * @param {boolean} [includeHidden=false] Not yet implemented
			 * @returns {FancytreeNode|null}
			 * @since v2.31
			 */
			findRelatedNode: function (node, where, includeHidden) {
				var res = null,
					KC = $.ui.keyCode;

				switch (where) {
					case "parent":
					case KC.BACKSPACE:
						if (node.parent && node.parent.parent) {
							res = node.parent;
						}
						break;
					case "first":
					case KC.HOME:
						// First visible node
						this.visit(function (n) {
							if (n.isVisible()) {
								res = n;
								return false;
							}
						});
						break;
					case "last":
					case KC.END:
						this.visit(function (n) {
							// last visible node
							if (n.isVisible()) {
								res = n;
							}
						});
						break;
					case "left":
					case KC.LEFT:
						if (node.expanded) {
							node.setExpanded(false);
						} else if (node.parent && node.parent.parent) {
							res = node.parent;
						}
						break;
					case "right":
					case KC.RIGHT:
						if (!node.expanded && (node.children || node.lazy)) {
							node.setExpanded();
							res = node;
						} else if (node.children && node.children.length) {
							res = node.children[0];
						}
						break;
					case "up":
					case KC.UP:
						this.visitRows(
							function (n) {
								res = n;
								return false;
							},
							{ start: node, reverse: true, includeSelf: false }
						);
						break;
					case "down":
					case KC.DOWN:
						this.visitRows(
							function (n) {
								res = n;
								return false;
							},
							{ start: node, includeSelf: false }
						);
						break;
					default:
						this.tree.warn("Unknown relation '" + where + "'.");
				}
				return res;
			},
			// TODO: fromDict
			/**
			 * Generate INPUT elements that can be submitted with html forms.
			 *
			 * In selectMode 3 only the topmost selected nodes are considered, unless
			 * `opts.stopOnParents: false` is passed.
			 *
			 * @example
			 * // Generate input elements for active and selected nodes
			 * tree.generateFormElements();
			 * // Generate input elements selected nodes, using a custom `name` attribute
			 * tree.generateFormElements("cust_sel", false);
			 * // Generate input elements using a custom filter
			 * tree.generateFormElements(true, true, { filter: function(node) {
			 *     return node.isSelected() && node.data.yes;
			 * }});
			 *
			 * @param {boolean | string} [selected=true] Pass false to disable, pass a string to override the field name (default: 'ft_ID[]')
			 * @param {boolean | string} [active=true] Pass false to disable, pass a string to override the field name (default: 'ft_ID_active')
			 * @param {object} [opts] default { filter: null, stopOnParents: true }
			 */
			generateFormElements: function (selected, active, opts) {
				opts = opts || {};

				var nodeList,
					selectedName =
						typeof selected === "string"
							? selected
							: "ft_" + this._id + "[]",
					activeName =
						typeof active === "string"
							? active
							: "ft_" + this._id + "_active",
					id = "fancytree_result_" + this._id,
					$result = $("#" + id),
					stopOnParents =
						this.options.selectMode === 3 &&
						opts.stopOnParents !== false;

				if ($result.length) {
					$result.empty();
				} else {
					$result = $("<div>", {
						id: id,
					})
						.hide()
						.insertAfter(this.$container);
				}
				if (active !== false && this.activeNode) {
					$result.append(
						$("<input>", {
							type: "radio",
							name: activeName,
							value: this.activeNode.key,
							checked: true,
						})
					);
				}
				function _appender(node) {
					$result.append(
						$("<input>", {
							type: "checkbox",
							name: selectedName,
							value: node.key,
							checked: true,
						})
					);
				}
				if (opts.filter) {
					this.visit(function (node) {
						var res = opts.filter(node);
						if (res === "skip") {
							return res;
						}
						if (res !== false) {
							_appender(node);
						}
					});
				} else if (selected !== false) {
					nodeList = this.getSelectedNodes(stopOnParents);
					$.each(nodeList, function (idx, node) {
						_appender(node);
					});
				}
			},
			/**
			 * Return the currently active node or null.
			 * @returns {FancytreeNode}
			 */
			getActiveNode: function () {
				return this.activeNode;
			},
			/** Return the first top level node if any (not the invisible root node).
			 * @returns {FancytreeNode | null}
			 */
			getFirstChild: function () {
				return this.rootNode.getFirstChild();
			},
			/**
			 * Return node that has keyboard focus or null.
			 * @returns {FancytreeNode}
			 */
			getFocusNode: function () {
				return this.focusNode;
			},
			/**
			 * Return current option value.
			 * (Note: this is the preferred variant of `$().fancytree("option", "KEY")`)
			 *
			 * @param {string} name option name (may contain '.')
			 * @returns {any}
			 */
			getOption: function (optionName) {
				return this.widget.option(optionName);
			},
			/**
			 * Return node with a given key or null if not found.
			 *
			 * @param {string} key
			 * @param {FancytreeNode} [searchRoot] only search below this node
			 * @returns {FancytreeNode | null}
			 */
			getNodeByKey: function (key, searchRoot) {
				// Search the DOM by element ID (assuming this is faster than traversing all nodes).
				var el, match;
				// TODO: use tree.keyMap if available
				// TODO: check opts.generateIds === true
				if (!searchRoot) {
					el = document.getElementById(this.options.idPrefix + key);
					if (el) {
						return el.ftnode ? el.ftnode : null;
					}
				}
				// Not found in the DOM, but still may be in an unrendered part of tree
				searchRoot = searchRoot || this.rootNode;
				match = null;
				key = "" + key; // Convert to string (#1005)
				searchRoot.visit(function (node) {
					if (node.key === key) {
						match = node;
						return false; // Stop iteration
					}
				}, true);
				return match;
			},
			/** Return the invisible system root node.
			 * @returns {FancytreeNode}
			 */
			getRootNode: function () {
				return this.rootNode;
			},
			/**
			 * Return an array of selected nodes.
			 *
			 * Note: you cannot send this result via Ajax directly. Instead the
			 * node object need to be converted to plain objects, for example
			 * by using `$.map()` and `node.toDict()`.
			 * @param {boolean} [stopOnParents=false] only return the topmost selected
			 *     node (useful with selectMode 3)
			 * @returns {FancytreeNode[]}
			 */
			getSelectedNodes: function (stopOnParents) {
				return this.rootNode.getSelectedNodes(stopOnParents);
			},
			/** Return true if the tree control has keyboard focus
			 * @returns {boolean}
			 */
			hasFocus: function () {
				// var ae = document.activeElement,
				// 	hasFocus = !!(
				// 		ae && $(ae).closest(".fancytree-container").length
				// 	);

				// if (hasFocus !== !!this._hasFocus) {
				// 	this.warn(
				// 		"hasFocus(): fix inconsistent container state, now: " +
				// 			hasFocus
				// 	);
				// 	this._hasFocus = hasFocus;
				// 	this.$container.toggleClass("fancytree-treefocus", hasFocus);
				// }
				// return hasFocus;
				return !!this._hasFocus;
			},
			/** Write to browser console if debugLevel >= 3 (prepending tree name)
			 * @param {*} msg string or object or array of such
			 */
			info: function (msg) {
				if (this.options.debugLevel >= 3) {
					Array.prototype.unshift.call(arguments, this.toString());
					consoleApply("info", arguments);
				}
			},
			/** Return true if any node is currently beeing loaded, i.e. a Ajax request is pending.
			 * @returns {boolean}
			 * @since 2.32
			 */
			isLoading: function () {
				var res = false;

				this.rootNode.visit(function (n) {
					// also visit rootNode
					if (n._isLoading || n._requestId) {
						res = true;
						return false;
					}
				}, true);
				return res;
			},
			/*
			TODO: isInitializing: function() {
				return ( this.phase=="init" || this.phase=="postInit" );
			},
			TODO: isReloading: function() {
				return ( this.phase=="init" || this.phase=="postInit" ) && this.options.persist && this.persistence.cookiesFound;
			},
			TODO: isUserEvent: function() {
				return ( this.phase=="userEvent" );
			},
			*/

			/**
			 * Make sure that a node with a given ID is loaded, by traversing - and
			 * loading - its parents. This method is meant for lazy hierarchies.
			 * A callback is executed for every node as we go.
			 * @example
			 * // Resolve using node.key:
			 * tree.loadKeyPath("/_3/_23/_26/_27", function(node, status){
			 *   if(status === "loaded") {
			 *     console.log("loaded intermediate node " + node);
			 *   }else if(status === "ok") {
			 *     node.activate();
			 *   }
			 * });
			 * // Use deferred promise:
			 * tree.loadKeyPath("/_3/_23/_26/_27").progress(function(data){
			 *   if(data.status === "loaded") {
			 *     console.log("loaded intermediate node " + data.node);
			 *   }else if(data.status === "ok") {
			 *     node.activate();
			 *   }
			 * }).done(function(){
			 *    ...
			 * });
			 * // Custom path segment resolver:
			 * tree.loadKeyPath("/321/431/21/2", {
			 *   matchKey: function(node, key){
			 *     return node.data.refKey === key;
			 *   },
			 *   callback: function(node, status){
			 *     if(status === "loaded") {
			 *       console.log("loaded intermediate node " + node);
			 *     }else if(status === "ok") {
			 *       node.activate();
			 *     }
			 *   }
			 * });
			 * @param {string | string[]} keyPathList one or more key paths (e.g. '/3/2_1/7')
			 * @param {function | object} optsOrCallback callback(node, status) is called for every visited node ('loading', 'loaded', 'ok', 'error').
			 *     Pass an object to define custom key matchers for the path segments: {callback: function, matchKey: function}.
			 * @returns {$.Promise}
			 */
			loadKeyPath: function (keyPathList, optsOrCallback) {
				var callback,
					i,
					path,
					self = this,
					dfd = new $.Deferred(),
					parent = this.getRootNode(),
					sep = this.options.keyPathSeparator,
					pathSegList = [],
					opts = $.extend({}, optsOrCallback);

				// Prepare options
				if (typeof optsOrCallback === "function") {
					callback = optsOrCallback;
				} else if (optsOrCallback && optsOrCallback.callback) {
					callback = optsOrCallback.callback;
				}
				opts.callback = function (ctx, node, status) {
					if (callback) {
						callback.call(ctx, node, status);
					}
					dfd.notifyWith(ctx, [{ node: node, status: status }]);
				};
				if (opts.matchKey == null) {
					opts.matchKey = function (node, key) {
						return node.key === key;
					};
				}
				// Convert array of path strings to array of segment arrays
				if (!_isArray(keyPathList)) {
					keyPathList = [keyPathList];
				}
				for (i = 0; i < keyPathList.length; i++) {
					path = keyPathList[i];
					// strip leading slash
					if (path.charAt(0) === sep) {
						path = path.substr(1);
					}
					// segListMap[path] = { parent: parent, segList: path.split(sep) };
					pathSegList.push(path.split(sep));
					// targetList.push({ parent: parent, segList: path.split(sep)/* , path: path*/});
				}
				// The timeout forces async behavior always (even if nodes are all loaded)
				// This way a potential progress() event will fire.
				setTimeout(function () {
					self._loadKeyPathImpl(dfd, opts, parent, pathSegList).done(
						function () {
							dfd.resolve();
						}
					);
				}, 0);
				return dfd.promise();
			},
			/*
			 * Resolve a list of paths, relative to one parent node.
			 */
			_loadKeyPathImpl: function (dfd, opts, parent, pathSegList) {
				var deferredList,
					i,
					key,
					node,
					nodeKey,
					remain,
					remainMap,
					tmpParent,
					segList,
					subDfd,
					self = this;

				function __findChild(parent, key) {
					// console.log("__findChild", key, parent);
					var i,
						l,
						cl = parent.children;

					if (cl) {
						for (i = 0, l = cl.length; i < l; i++) {
							if (opts.matchKey(cl[i], key)) {
								return cl[i];
							}
						}
					}
					return null;
				}

				// console.log("_loadKeyPathImpl, parent=", parent, ", pathSegList=", pathSegList);

				// Pass 1:
				// Handle all path segments for nodes that are already loaded.
				// Collect distinct top-most lazy nodes in a map.
				// Note that we can use node.key to de-dupe entries, even if a custom matcher would
				// look for other node attributes.
				// map[node.key] => {node: node, pathList: [list of remaining rest-paths]}
				remainMap = {};

				for (i = 0; i < pathSegList.length; i++) {
					segList = pathSegList[i];
					// target = targetList[i];

					// Traverse and pop path segments (i.e. keys), until we hit a lazy, unloaded node
					tmpParent = parent;
					while (segList.length) {
						key = segList.shift();
						node = __findChild(tmpParent, key);
						if (!node) {
							this.warn(
								"loadKeyPath: key not found: " +
									key +
									" (parent: " +
									tmpParent +
									")"
							);
							opts.callback(this, key, "error");
							break;
						} else if (segList.length === 0) {
							opts.callback(this, node, "ok");
							break;
						} else if (!node.lazy || node.hasChildren() !== undefined) {
							opts.callback(this, node, "loaded");
							tmpParent = node;
						} else {
							opts.callback(this, node, "loaded");
							key = node.key; //target.segList.join(sep);
							if (remainMap[key]) {
								remainMap[key].pathSegList.push(segList);
							} else {
								remainMap[key] = {
									parent: node,
									pathSegList: [segList],
								};
							}
							break;
						}
					}
				}
				// console.log("_loadKeyPathImpl AFTER pass 1, remainMap=", remainMap);

				// Now load all lazy nodes and continue iteration for remaining paths
				deferredList = [];

				// Avoid jshint warning 'Don't make functions within a loop.':
				function __lazyload(dfd, parent, pathSegList) {
					// console.log("__lazyload", parent, "pathSegList=", pathSegList);
					opts.callback(self, parent, "loading");
					parent
						.load()
						.done(function () {
							self._loadKeyPathImpl
								.call(self, dfd, opts, parent, pathSegList)
								.always(_makeResolveFunc(dfd, self));
						})
						.fail(function (errMsg) {
							self.warn("loadKeyPath: error loading lazy " + parent);
							opts.callback(self, node, "error");
							dfd.rejectWith(self);
						});
				}
				// remainMap contains parent nodes, each with a list of relative sub-paths.
				// We start loading all of them now, and pass the the list to each loader.
				for (nodeKey in remainMap) {
					if (_hasProp(remainMap, nodeKey)) {
						remain = remainMap[nodeKey];
						// console.log("for(): remain=", remain, "remainMap=", remainMap);
						// key = remain.segList.shift();
						// node = __findChild(remain.parent, key);
						// if (node == null) {  // #576
						// 	// Issue #576, refactored for v2.27:
						// 	// The root cause was, that sometimes the wrong parent was used here
						// 	// to find the next segment.
						// 	// Falling back to getNodeByKey() was a hack that no longer works if a custom
						// 	// matcher is used, because we cannot assume that a single segment-key is unique
						// 	// throughout the tree.
						// 	self.error("loadKeyPath: error loading child by key '" + key + "' (parent: " + target.parent + ")", target);
						// 	// 	node = self.getNodeByKey(key);
						// 	continue;
						// }
						subDfd = new $.Deferred();
						deferredList.push(subDfd);
						__lazyload(subDfd, remain.parent, remain.pathSegList);
					}
				}
				// Return a promise that is resolved, when ALL paths were loaded
				return $.when.apply($, deferredList).promise();
			},
			/** Re-fire beforeActivate, activate, and (optional) focus events.
			 * Calling this method in the `init` event, will activate the node that
			 * was marked 'active' in the source data, and optionally set the keyboard
			 * focus.
			 * @param [setFocus=false]
			 */
			reactivate: function (setFocus) {
				var res,
					node = this.activeNode;

				if (!node) {
					return _getResolvedPromise();
				}
				this.activeNode = null; // Force re-activating
				res = node.setActive(true, { noFocus: true });
				if (setFocus) {
					node.setFocus();
				}
				return res;
			},
			/** Reload tree from source and return a promise.
			 * @param [source] optional new source (defaults to initial source data)
			 * @returns {$.Promise}
			 */
			reload: function (source) {
				this._callHook("treeClear", this);
				return this._callHook("treeLoad", this, source);
			},
			/**Render tree (i.e. create DOM elements for all top-level nodes).
			 * @param {boolean} [force=false] create DOM elemnts, even if parent is collapsed
			 * @param {boolean} [deep=false]
			 */
			render: function (force, deep) {
				return this.rootNode.render(force, deep);
			},
			/**(De)select all nodes.
			 * @param {boolean} [flag=true]
			 * @since 2.28
			 */
			selectAll: function (flag) {
				this.visit(function (node) {
					node.setSelected(flag);
				});
			},
			// TODO: selectKey: function(key, select)
			// TODO: serializeArray: function(stopOnParents)
			/**
			 * @param {boolean} [flag=true]
			 */
			setFocus: function (flag) {
				return this._callHook("treeSetFocus", this, flag);
			},
			/**
			 * Set current option value.
			 * (Note: this is the preferred variant of `$().fancytree("option", "KEY", VALUE)`)
			 * @param {string} name option name (may contain '.')
			 * @param {any} new value
			 */
			setOption: function (optionName, value) {
				return this.widget.option(optionName, value);
			},
			/**
			 * Call console.time() when in debug mode (verbose >= 4).
			 *
			 * @param {string} label
			 */
			debugTime: function (label) {
				if (this.options.debugLevel >= 4) {
					window.console.time(this + " - " + label);
				}
			},
			/**
			 * Call console.timeEnd() when in debug mode (verbose >= 4).
			 *
			 * @param {string} label
			 */
			debugTimeEnd: function (label) {
				if (this.options.debugLevel >= 4) {
					window.console.timeEnd(this + " - " + label);
				}
			},
			/**
			 * Return all nodes as nested list of {@link NodeData}.
			 *
			 * @param {boolean} [includeRoot=false] Returns the hidden system root node (and its children)
			 * @param {function} [callback] callback(dict, node) is called for every node, in order to allow modifications.
			 *     Return `false` to ignore this node or "skip" to include this node without its children.
			 * @returns {Array | object}
			 * @see FancytreeNode#toDict
			 */
			toDict: function (includeRoot, callback) {
				var res = this.rootNode.toDict(true, callback);
				return includeRoot ? res : res.children;
			},
			/* Implicitly called for string conversions.
			 * @returns {string}
			 */
			toString: function () {
				return "Fancytree@" + this._id;
				// return "<Fancytree(#" + this._id + ")>";
			},
			/* _trigger a widget event with additional node ctx.
			 * @see EventData
			 */
			_triggerNodeEvent: function (type, node, originalEvent, extra) {
				// this.debug("_trigger(" + type + "): '" + ctx.node.title + "'", ctx);
				var ctx = this._makeHookContext(node, originalEvent, extra),
					res = this.widget._trigger(type, originalEvent, ctx);
				if (res !== false && ctx.result !== undefined) {
					return ctx.result;
				}
				return res;
			},
			/* _trigger a widget event with additional tree data. */
			_triggerTreeEvent: function (type, originalEvent, extra) {
				// this.debug("_trigger(" + type + ")", ctx);
				var ctx = this._makeHookContext(this, originalEvent, extra),
					res = this.widget._trigger(type, originalEvent, ctx);

				if (res !== false && ctx.result !== undefined) {
					return ctx.result;
				}
				return res;
			},
			/** Call fn(node) for all nodes in hierarchical order (depth-first).
			 *
			 * @param {function} fn the callback function.
			 *     Return false to stop iteration, return "skip" to skip this node and children only.
			 * @returns {boolean} false, if the iterator was stopped.
			 */
			visit: function (fn) {
				return this.rootNode.visit(fn, false);
			},
			/** Call fn(node) for all nodes in vertical order, top down (or bottom up).<br>
			 * Stop iteration, if fn() returns false.<br>
			 * Return false if iteration was stopped.
			 *
			 * @param {function} fn the callback function.
			 *     Return false to stop iteration, return "skip" to skip this node and children only.
			 * @param {object} [options]
			 *     Defaults:
			 *     {start: First top node, reverse: false, includeSelf: true, includeHidden: false}
			 * @returns {boolean} false if iteration was cancelled
			 * @since 2.28
			 */
			visitRows: function (fn, opts) {
				if (!this.rootNode.hasChildren()) {
					return false;
				}
				if (opts && opts.reverse) {
					delete opts.reverse;
					return this._visitRowsUp(fn, opts);
				}
				opts = opts || {};

				var i,
					nextIdx,
					parent,
					res,
					siblings,
					siblingOfs = 0,
					skipFirstNode = opts.includeSelf === false,
					includeHidden = !!opts.includeHidden,
					checkFilter = !includeHidden && this.enableFilter,
					node = opts.start || this.rootNode.children[0];

				parent = node.parent;
				while (parent) {
					// visit siblings
					siblings = parent.children;
					nextIdx = siblings.indexOf(node) + siblingOfs;
					_assert(
						nextIdx >= 0,
						"Could not find " +
							node +
							" in parent's children: " +
							parent
					);

					for (i = nextIdx; i < siblings.length; i++) {
						node = siblings[i];
						if (checkFilter && !node.match && !node.subMatchCount) {
							continue;
						}
						if (!skipFirstNode && fn(node) === false) {
							return false;
						}
						skipFirstNode = false;
						// Dive into node's child nodes
						if (
							node.children &&
							node.children.length &&
							(includeHidden || node.expanded)
						) {
							// Disable warning: Functions declared within loops referencing an outer
							// scoped variable may lead to confusing semantics:
							/*jshint -W083 */
							res = node.visit(function (n) {
								if (checkFilter && !n.match && !n.subMatchCount) {
									return "skip";
								}
								if (fn(n) === false) {
									return false;
								}
								if (!includeHidden && n.children && !n.expanded) {
									return "skip";
								}
							}, false);
							/*jshint +W083 */
							if (res === false) {
								return false;
							}
						}
					}
					// Visit parent nodes (bottom up)
					node = parent;
					parent = parent.parent;
					siblingOfs = 1; //
				}
				return true;
			},
			/* Call fn(node) for all nodes in vertical order, bottom up.
			 */
			_visitRowsUp: function (fn, opts) {
				var children,
					idx,
					parent,
					includeHidden = !!opts.includeHidden,
					node = opts.start || this.rootNode.children[0];

				while (true) {
					parent = node.parent;
					children = parent.children;

					if (children[0] === node) {
						// If this is already the first sibling, goto parent
						node = parent;
						if (!node.parent) {
							break; // first node of the tree
						}
						children = parent.children;
					} else {
						// Otherwise, goto prev. sibling
						idx = children.indexOf(node);
						node = children[idx - 1];
						// If the prev. sibling has children, follow down to last descendant
						while (
							// See: https://github.com/eslint/eslint/issues/11302
							// eslint-disable-next-line no-unmodified-loop-condition
							(includeHidden || node.expanded) &&
							node.children &&
							node.children.length
						) {
							children = node.children;
							parent = node;
							node = children[children.length - 1];
						}
					}
					// Skip invisible
					if (!includeHidden && !node.isVisible()) {
						continue;
					}
					if (fn(node) === false) {
						return false;
					}
				}
			},
			/** Write warning to browser console if debugLevel >= 2 (prepending tree info)
			 *
			 * @param {*} msg string or object or array of such
			 */
			warn: function (msg) {
				if (this.options.debugLevel >= 2) {
					Array.prototype.unshift.call(arguments, this.toString());
					consoleApply("warn", arguments);
				}
			},
		};

		/**
		 * These additional methods of the {@link Fancytree} class are 'hook functions'
		 * that can be used and overloaded by extensions.
		 *
		 * @see [writing extensions](https://github.com/mar10/fancytree/wiki/TutorialExtensions)
		 * @mixin Fancytree_Hooks
		 */
		$.extend(
			Fancytree.prototype,
			/** @lends Fancytree_Hooks# */
			{
				/** Default handling for mouse click events.
				 *
				 * @param {EventData} ctx
				 */
				nodeClick: function (ctx) {
					var activate,
						expand,
						// event = ctx.originalEvent,
						targetType = ctx.targetType,
						node = ctx.node;

					// this.debug("ftnode.onClick(" + event.type + "): ftnode:" + this + ", button:" + event.button + ", which: " + event.which, ctx);
					// TODO: use switch
					// TODO: make sure clicks on embedded <input> doesn't steal focus (see table sample)
					if (targetType === "expander") {
						if (node.isLoading()) {
							// #495: we probably got a click event while a lazy load is pending.
							// The 'expanded' state is not yet set, so 'toggle' would expand
							// and trigger lazyLoad again.
							// It would be better to allow to collapse/expand the status node
							// while loading (instead of ignoring), but that would require some
							// more work.
							node.debug("Got 2nd click while loading: ignored");
							return;
						}
						// Clicking the expander icon always expands/collapses
						this._callHook("nodeToggleExpanded", ctx);
					} else if (targetType === "checkbox") {
						// Clicking the checkbox always (de)selects
						this._callHook("nodeToggleSelected", ctx);
						if (ctx.options.focusOnSelect) {
							// #358
							this._callHook("nodeSetFocus", ctx, true);
						}
					} else {
						// Honor `clickFolderMode` for
						expand = false;
						activate = true;
						if (node.folder) {
							switch (ctx.options.clickFolderMode) {
								case 2: // expand only
									expand = true;
									activate = false;
									break;
								case 3: // expand and activate
									activate = true;
									expand = true; //!node.isExpanded();
									break;
								// else 1 or 4: just activate
							}
						}
						if (activate) {
							this.nodeSetFocus(ctx);
							this._callHook("nodeSetActive", ctx, true);
						}
						if (expand) {
							if (!activate) {
								// this._callHook("nodeSetFocus", ctx);
							}
							// this._callHook("nodeSetExpanded", ctx, true);
							this._callHook("nodeToggleExpanded", ctx);
						}
					}
					// Make sure that clicks stop, otherwise <a href='#'> jumps to the top
					// if(event.target.localName === "a" && event.target.className === "fancytree-title"){
					// 	event.preventDefault();
					// }
					// TODO: return promise?
				},
				/** Collapse all other  children of same parent.
				 *
				 * @param {EventData} ctx
				 * @param {object} callOpts
				 */
				nodeCollapseSiblings: function (ctx, callOpts) {
					// TODO: return promise?
					var ac,
						i,
						l,
						node = ctx.node;

					if (node.parent) {
						ac = node.parent.children;
						for (i = 0, l = ac.length; i < l; i++) {
							if (ac[i] !== node && ac[i].expanded) {
								this._callHook(
									"nodeSetExpanded",
									ac[i],
									false,
									callOpts
								);
							}
						}
					}
				},
				/** Default handling for mouse douleclick events.
				 * @param {EventData} ctx
				 */
				nodeDblclick: function (ctx) {
					// TODO: return promise?
					if (
						ctx.targetType === "title" &&
						ctx.options.clickFolderMode === 4
					) {
						// this.nodeSetFocus(ctx);
						// this._callHook("nodeSetActive", ctx, true);
						this._callHook("nodeToggleExpanded", ctx);
					}
					// TODO: prevent text selection on dblclicks
					if (ctx.targetType === "title") {
						ctx.originalEvent.preventDefault();
					}
				},
				/** Default handling for mouse keydown events.
				 *
				 * NOTE: this may be called with node == null if tree (but no node) has focus.
				 * @param {EventData} ctx
				 */
				nodeKeydown: function (ctx) {
					// TODO: return promise?
					var matchNode,
						stamp,
						_res,
						focusNode,
						event = ctx.originalEvent,
						node = ctx.node,
						tree = ctx.tree,
						opts = ctx.options,
						which = event.which,
						// #909: Use event.key, to get unicode characters.
						// We can't use `/\w/.test(key)`, because that would
						// only detect plain ascii alpha-numerics. But we still need
						// to ignore modifier-only, whitespace, cursor-keys, etc.
						key = event.key || String.fromCharCode(which),
						specialModifiers = !!(
							event.altKey ||
							event.ctrlKey ||
							event.metaKey
						),
						isAlnum =
							!MODIFIERS[which] &&
							!SPECIAL_KEYCODES[which] &&
							!specialModifiers,
						$target = $(event.target),
						handled = true,
						activate = !(event.ctrlKey || !opts.autoActivate);

					// (node || FT).debug("ftnode.nodeKeydown(" + event.type + "): ftnode:" + this + ", charCode:" + event.charCode + ", keyCode: " + event.keyCode + ", which: " + event.which);
					// FT.debug( "eventToString(): " + FT.eventToString(event) + ", key='" + key + "', isAlnum: " + isAlnum );

					// Set focus to active (or first node) if no other node has the focus yet
					if (!node) {
						focusNode = this.getActiveNode() || this.getFirstChild();
						if (focusNode) {
							focusNode.setFocus();
							node = ctx.node = this.focusNode;
							node.debug("Keydown force focus on active node");
						}
					}

					if (
						opts.quicksearch &&
						isAlnum &&
						!$target.is(":input:enabled")
					) {
						// Allow to search for longer streaks if typed in quickly
						stamp = Date.now();
						if (stamp - tree.lastQuicksearchTime > 500) {
							tree.lastQuicksearchTerm = "";
						}
						tree.lastQuicksearchTime = stamp;
						tree.lastQuicksearchTerm += key;
						// tree.debug("quicksearch find", tree.lastQuicksearchTerm);
						matchNode = tree.findNextNode(
							tree.lastQuicksearchTerm,
							tree.getActiveNode()
						);
						if (matchNode) {
							matchNode.setActive();
						}
						event.preventDefault();
						return;
					}
					switch (FT.eventToString(event)) {
						case "+":
						case "=": // 187: '+' @ Chrome, Safari
							tree.nodeSetExpanded(ctx, true);
							break;
						case "-":
							tree.nodeSetExpanded(ctx, false);
							break;
						case "space":
							if (node.isPagingNode()) {
								tree._triggerNodeEvent("clickPaging", ctx, event);
							} else if (
								FT.evalOption("checkbox", node, node, opts, false)
							) {
								// #768
								tree.nodeToggleSelected(ctx);
							} else {
								tree.nodeSetActive(ctx, true);
							}
							break;
						case "return":
							tree.nodeSetActive(ctx, true);
							break;
						case "home":
						case "end":
						case "backspace":
						case "left":
						case "right":
						case "up":
						case "down":
							_res = node.navigate(event.which, activate);
							break;
						default:
							handled = false;
					}
					if (handled) {
						event.preventDefault();
					}
				},

				// /** Default handling for mouse keypress events. */
				// nodeKeypress: function(ctx) {
				//     var event = ctx.originalEvent;
				// },

				// /** Trigger lazyLoad event (async). */
				// nodeLazyLoad: function(ctx) {
				//     var node = ctx.node;
				//     if(this._triggerNodeEvent())
				// },
				/** Load child nodes (async).
				 *
				 * @param {EventData} ctx
				 * @param {object[]|object|string|$.Promise|function} source
				 * @returns {$.Promise} The deferred will be resolved as soon as the (ajax)
				 *     data was rendered.
				 */
				nodeLoadChildren: function (ctx, source) {
					var ajax,
						delay,
						ajaxDfd = null,
						resultDfd,
						isAsync = true,
						tree = ctx.tree,
						node = ctx.node,
						nodePrevParent = node.parent,
						tag = "nodeLoadChildren",
						requestId = Date.now();

					// `source` is a callback: use the returned result instead:
					if (_isFunction(source)) {
						source = source.call(tree, { type: "source" }, ctx);
						_assert(
							!_isFunction(source),
							"source callback must not return another function"
						);
					}
					// `source` is already a promise:
					if (_isFunction(source.then)) {
						// _assert(_isFunction(source.always), "Expected jQuery?");
						ajaxDfd = source;
					} else if (source.url) {
						// `source` is an Ajax options object
						ajax = $.extend({}, ctx.options.ajax, source);
						if (ajax.debugDelay) {
							// Simulate a slow server
							delay = ajax.debugDelay;
							delete ajax.debugDelay; // remove debug option
							if (_isArray(delay)) {
								// random delay range [min..max]
								delay =
									delay[0] +
									Math.random() * (delay[1] - delay[0]);
							}
							node.warn(
								"nodeLoadChildren waiting debugDelay " +
									Math.round(delay) +
									" ms ..."
							);
							ajaxDfd = $.Deferred(function (ajaxDfd) {
								setTimeout(function () {
									$.ajax(ajax)
										.done(function () {
											ajaxDfd.resolveWith(this, arguments);
										})
										.fail(function () {
											ajaxDfd.rejectWith(this, arguments);
										});
								}, delay);
							});
						} else {
							ajaxDfd = $.ajax(ajax);
						}
					} else if ($.isPlainObject(source) || _isArray(source)) {
						// `source` is already a constant dict or list, but we convert
						// to a thenable for unified processing.
						// 2020-01-03: refactored.
						// `ajaxDfd = $.when(source)` would do the trick, but the returned
						// promise will resolve async, which broke some tests and
						// would probably also break current implementations out there.
						// So we mock-up a thenable that resolves synchronously:
						ajaxDfd = {
							then: function (resolve, reject) {
								resolve(source, null, null);
							},
						};
						isAsync = false;
					} else {
						$.error("Invalid source type: " + source);
					}

					// Check for overlapping requests
					if (node._requestId) {
						node.warn(
							"Recursive load request #" +
								requestId +
								" while #" +
								node._requestId +
								" is pending."
						);
						node._requestId = requestId;
						// 	node.debug("Send load request #" + requestId);
					}

					if (isAsync) {
						tree.debugTime(tag);
						tree.nodeSetStatus(ctx, "loading");
					}

					// The async Ajax request has now started...
					// Defer the deferred:
					// we want to be able to reject invalid responses, even if
					// the raw HTTP Ajax XHR resolved as Ok.
					// We use the ajaxDfd.then() syntax here, which is compatible with
					// jQuery and ECMA6.
					// However resultDfd is a jQuery deferred, which is currently the
					// expected result type of nodeLoadChildren()
					resultDfd = new $.Deferred();
					ajaxDfd.then(
						function (data, textStatus, jqXHR) {
							// ajaxDfd was resolved, but we reject or resolve resultDfd
							// depending on the response data
							var errorObj, res;

							if (
								(source.dataType === "json" ||
									source.dataType === "jsonp") &&
								typeof data === "string"
							) {
								$.error(
									"Ajax request returned a string (did you get the JSON dataType wrong?)."
								);
							}
							if (node._requestId && node._requestId > requestId) {
								// The expected request time stamp is later than `requestId`
								// (which was kept as as closure variable to this handler function)
								// node.warn("Ignored load response for obsolete request #" + requestId + " (expected #" + node._requestId + ")");
								resultDfd.rejectWith(this, [
									RECURSIVE_REQUEST_ERROR,
								]);
								return;
								// } else {
								// 	node.debug("Response returned for load request #" + requestId);
							}
							if (node.parent === null && nodePrevParent !== null) {
								resultDfd.rejectWith(this, [
									INVALID_REQUEST_TARGET_ERROR,
								]);
								return;
							}
							// Allow to adjust the received response data in the `postProcess` event.
							if (ctx.options.postProcess) {
								// The handler may either
								//   - modify `ctx.response` in-place (and leave `ctx.result` undefined)
								//     => res = undefined
								//   - return a replacement in `ctx.result`
								//     => res = <new data>
								//   If res contains an `error` property, an error status is displayed
								try {
									res = tree._triggerNodeEvent(
										"postProcess",
										ctx,
										ctx.originalEvent,
										{
											response: data,
											error: null,
											dataType: source.dataType,
										}
									);
									if (res.error) {
										tree.warn(
											"postProcess returned error:",
											res
										);
									}
								} catch (e) {
									res = {
										error: e,
										message: "" + e,
										details: "postProcess failed",
									};
								}
								if (res.error) {
									// Either postProcess failed with an exception, or the returned
									// result object has an 'error' property attached:
									errorObj = $.isPlainObject(res.error)
										? res.error
										: { message: res.error };
									errorObj = tree._makeHookContext(
										node,
										null,
										errorObj
									);
									resultDfd.rejectWith(this, [errorObj]);
									return;
								}
								if (
									_isArray(res) ||
									($.isPlainObject(res) && _isArray(res.children))
								) {
									// Use `ctx.result` if valid
									// (otherwise use existing data, which may have been modified in-place)
									data = res;
								}
							} else if (
								data &&
								_hasProp(data, "d") &&
								ctx.options.enableAspx
							) {
								// Process ASPX WebMethod JSON object inside "d" property
								// (only if no postProcess event was defined)
								if (ctx.options.enableAspx === 42) {
									tree.warn(
										"The default for enableAspx will change to `false` in the fututure. " +
											"Pass `enableAspx: true` or implement postProcess to silence this warning."
									);
								}
								data =
									typeof data.d === "string"
										? $.parseJSON(data.d)
										: data.d;
							}
							resultDfd.resolveWith(this, [data]);
						},
						function (jqXHR, textStatus, errorThrown) {
							// ajaxDfd was rejected, so we reject resultDfd as well
							var errorObj = tree._makeHookContext(node, null, {
								error: jqXHR,
								args: Array.prototype.slice.call(arguments),
								message: errorThrown,
								details: jqXHR.status + ": " + errorThrown,
							});
							resultDfd.rejectWith(this, [errorObj]);
						}
					);

					// The async Ajax request has now started.
					// resultDfd will be resolved/rejected after the response arrived,
					// was postProcessed, and checked.
					// Now we implement the UI update and add the data to the tree.
					// We also return this promise to the caller.
					resultDfd
						.done(function (data) {
							tree.nodeSetStatus(ctx, "ok");
							var children, metaData, noDataRes;

							if ($.isPlainObject(data)) {
								// We got {foo: 'abc', children: [...]}
								// Copy extra properties to tree.data.foo
								_assert(
									node.isRootNode(),
									"source may only be an object for root nodes (expecting an array of child objects otherwise)"
								);
								_assert(
									_isArray(data.children),
									"if an object is passed as source, it must contain a 'children' array (all other properties are added to 'tree.data')"
								);
								metaData = data;
								children = data.children;
								delete metaData.children;
								// Copy some attributes to tree.data
								$.each(TREE_ATTRS, function (i, attr) {
									if (metaData[attr] !== undefined) {
										tree[attr] = metaData[attr];
										delete metaData[attr];
									}
								});
								// Copy all other attributes to tree.data.NAME
								$.extend(tree.data, metaData);
							} else {
								children = data;
							}
							_assert(
								_isArray(children),
								"expected array of children"
							);
							node._setChildren(children);

							if (tree.options.nodata && children.length === 0) {
								if (_isFunction(tree.options.nodata)) {
									noDataRes = tree.options.nodata.call(
										tree,
										{ type: "nodata" },
										ctx
									);
								} else if (
									tree.options.nodata === true &&
									node.isRootNode()
								) {
									noDataRes = tree.options.strings.noData;
								} else if (
									typeof tree.options.nodata === "string" &&
									node.isRootNode()
								) {
									noDataRes = tree.options.nodata;
								}
								if (noDataRes) {
									node.setStatus("nodata", noDataRes);
								}
							}
							// trigger fancytreeloadchildren
							tree._triggerNodeEvent("loadChildren", node);
						})
						.fail(function (error) {
							var ctxErr;

							if (error === RECURSIVE_REQUEST_ERROR) {
								node.warn(
									"Ignored response for obsolete load request #" +
										requestId +
										" (expected #" +
										node._requestId +
										")"
								);
								return;
							} else if (error === INVALID_REQUEST_TARGET_ERROR) {
								node.warn(
									"Lazy parent node was removed while loading: discarding response."
								);
								return;
							} else if (error.node && error.error && error.message) {
								// error is already a context object
								ctxErr = error;
							} else {
								ctxErr = tree._makeHookContext(node, null, {
									error: error, // it can be jqXHR or any custom error
									args: Array.prototype.slice.call(arguments),
									message: error
										? error.message || error.toString()
										: "",
								});
								if (ctxErr.message === "[object Object]") {
									ctxErr.message = "";
								}
							}
							node.warn(
								"Load children failed (" + ctxErr.message + ")",
								ctxErr
							);
							if (
								tree._triggerNodeEvent(
									"loadError",
									ctxErr,
									null
								) !== false
							) {
								tree.nodeSetStatus(
									ctx,
									"error",
									ctxErr.message,
									ctxErr.details
								);
							}
						})
						.always(function () {
							node._requestId = null;
							if (isAsync) {
								tree.debugTimeEnd(tag);
							}
						});

					return resultDfd.promise();
				},
				/** [Not Implemented]  */
				nodeLoadKeyPath: function (ctx, keyPathList) {
					// TODO: implement and improve
					// http://code.google.com/p/dynatree/issues/detail?id=222
				},
				/**
				 * Remove a single direct child of ctx.node.
				 * @param {EventData} ctx
				 * @param {FancytreeNode} childNode dircect child of ctx.node
				 */
				nodeRemoveChild: function (ctx, childNode) {
					var idx,
						node = ctx.node,
						// opts = ctx.options,
						subCtx = $.extend({}, ctx, { node: childNode }),
						children = node.children;

					// FT.debug("nodeRemoveChild()", node.toString(), childNode.toString());

					if (children.length === 1) {
						_assert(childNode === children[0], "invalid single child");
						return this.nodeRemoveChildren(ctx);
					}
					if (
						this.activeNode &&
						(childNode === this.activeNode ||
							this.activeNode.isDescendantOf(childNode))
					) {
						this.activeNode.setActive(false); // TODO: don't fire events
					}
					if (
						this.focusNode &&
						(childNode === this.focusNode ||
							this.focusNode.isDescendantOf(childNode))
					) {
						this.focusNode = null;
					}
					// TODO: persist must take care to clear select and expand cookies
					this.nodeRemoveMarkup(subCtx);
					this.nodeRemoveChildren(subCtx);
					idx = $.inArray(childNode, children);
					_assert(idx >= 0, "invalid child");
					// Notify listeners
					node.triggerModifyChild("remove", childNode);
					// Unlink to support GC
					childNode.visit(function (n) {
						n.parent = null;
					}, true);
					this._callHook("treeRegisterNode", this, false, childNode);
					// remove from child list
					children.splice(idx, 1);
				},
				/**Remove HTML markup for all descendents of ctx.node.
				 * @param {EventData} ctx
				 */
				nodeRemoveChildMarkup: function (ctx) {
					var node = ctx.node;

					// FT.debug("nodeRemoveChildMarkup()", node.toString());
					// TODO: Unlink attr.ftnode to support GC
					if (node.ul) {
						if (node.isRootNode()) {
							$(node.ul).empty();
						} else {
							$(node.ul).remove();
							node.ul = null;
						}
						node.visit(function (n) {
							n.li = n.ul = null;
						});
					}
				},
				/**Remove all descendants of ctx.node.
				 * @param {EventData} ctx
				 */
				nodeRemoveChildren: function (ctx) {
					var //subCtx,
						tree = ctx.tree,
						node = ctx.node,
						children = node.children;
					// opts = ctx.options;

					// FT.debug("nodeRemoveChildren()", node.toString());
					if (!children) {
						return;
					}
					if (this.activeNode && this.activeNode.isDescendantOf(node)) {
						this.activeNode.setActive(false); // TODO: don't fire events
					}
					if (this.focusNode && this.focusNode.isDescendantOf(node)) {
						this.focusNode = null;
					}
					// TODO: persist must take care to clear select and expand cookies
					this.nodeRemoveChildMarkup(ctx);
					// Unlink children to support GC
					// TODO: also delete this.children (not possible using visit())
					// subCtx = $.extend({}, ctx);
					node.triggerModifyChild("remove", null);
					node.visit(function (n) {
						n.parent = null;
						tree._callHook("treeRegisterNode", tree, false, n);
					});
					if (node.lazy) {
						// 'undefined' would be interpreted as 'not yet loaded' for lazy nodes
						node.children = [];
					} else {
						node.children = null;
					}
					if (!node.isRootNode()) {
						node.expanded = false; // #449, #459
					}
					this.nodeRenderStatus(ctx);
				},
				/**Remove HTML markup for ctx.node and all its descendents.
				 * @param {EventData} ctx
				 */
				nodeRemoveMarkup: function (ctx) {
					var node = ctx.node;
					// FT.debug("nodeRemoveMarkup()", node.toString());
					// TODO: Unlink attr.ftnode to support GC
					if (node.li) {
						$(node.li).remove();
						node.li = null;
					}
					this.nodeRemoveChildMarkup(ctx);
				},
				/**
				 * Create `<li><span>..</span> .. </li>` tags for this node.
				 *
				 * This method takes care that all HTML markup is created that is required
				 * to display this node in its current state.
				 *
				 * Call this method to create new nodes, or after the strucuture
				 * was changed (e.g. after moving this node or adding/removing children)
				 * nodeRenderTitle() and nodeRenderStatus() are implied.
				 *
				 * ```html
				 * <li id='KEY' ftnode=NODE>
				 *     <span class='fancytree-node fancytree-expanded fancytree-has-children fancytree-lastsib fancytree-exp-el fancytree-ico-e'>
				 *         <span class="fancytree-expander"></span>
				 *         <span class="fancytree-checkbox"></span> // only present in checkbox mode
				 *         <span class="fancytree-icon"></span>
				 *         <a href="#" class="fancytree-title"> Node 1 </a>
				 *     </span>
				 *     <ul> // only present if node has children
				 *         <li id='KEY' ftnode=NODE> child1 ... </li>
				 *         <li id='KEY' ftnode=NODE> child2 ... </li>
				 *     </ul>
				 * </li>
				 * ```
				 *
				 * @param {EventData} ctx
				 * @param {boolean} [force=false] re-render, even if html markup was already created
				 * @param {boolean} [deep=false] also render all descendants, even if parent is collapsed
				 * @param {boolean} [collapsed=false] force root node to be collapsed, so we can apply animated expand later
				 */
				nodeRender: function (ctx, force, deep, collapsed, _recursive) {
					/* This method must take care of all cases where the current data mode
					 * (i.e. node hierarchy) does not match the current markup.
					 *
					 * - node was not yet rendered:
					 *   create markup
					 * - node was rendered: exit fast
					 * - children have been added
					 * - children have been removed
					 */
					var childLI,
						childNode1,
						childNode2,
						i,
						l,
						next,
						subCtx,
						node = ctx.node,
						tree = ctx.tree,
						opts = ctx.options,
						aria = opts.aria,
						firstTime = false,
						parent = node.parent,
						isRootNode = !parent,
						children = node.children,
						successorLi = null;
					// FT.debug("nodeRender(" + !!force + ", " + !!deep + ")", node.toString());

					if (tree._enableUpdate === false) {
						// tree.debug("no render", tree._enableUpdate);
						return;
					}
					if (!isRootNode && !parent.ul) {
						// Calling node.collapse on a deep, unrendered node
						return;
					}
					_assert(isRootNode || parent.ul, "parent UL must exist");

					// Render the node
					if (!isRootNode) {
						// Discard markup on force-mode, or if it is not linked to parent <ul>
						if (
							node.li &&
							(force || node.li.parentNode !== node.parent.ul)
						) {
							if (node.li.parentNode === node.parent.ul) {
								// #486: store following node, so we can insert the new markup there later
								successorLi = node.li.nextSibling;
							} else {
								// May happen, when a top-level node was dropped over another
								this.debug(
									"Unlinking " +
										node +
										" (must be child of " +
										node.parent +
										")"
								);
							}
							//	            this.debug("nodeRemoveMarkup...");
							this.nodeRemoveMarkup(ctx);
						}
						// Create <li><span /> </li>
						// node.debug("render...");
						if (node.li) {
							// this.nodeRenderTitle(ctx);
							this.nodeRenderStatus(ctx);
						} else {
							// node.debug("render... really");
							firstTime = true;
							node.li = document.createElement("li");
							node.li.ftnode = node;

							if (node.key && opts.generateIds) {
								node.li.id = opts.idPrefix + node.key;
							}
							node.span = document.createElement("span");
							node.span.className = "fancytree-node";
							if (aria && !node.tr) {
								$(node.li).attr("role", "treeitem");
							}
							node.li.appendChild(node.span);

							// Create inner HTML for the <span> (expander, checkbox, icon, and title)
							this.nodeRenderTitle(ctx);

							// Allow tweaking and binding, after node was created for the first time
							if (opts.createNode) {
								opts.createNode.call(
									tree,
									{ type: "createNode" },
									ctx
								);
							}
						}
						// Allow tweaking after node state was rendered
						if (opts.renderNode) {
							opts.renderNode.call(tree, { type: "renderNode" }, ctx);
						}
					}

					// Visit child nodes
					if (children) {
						if (isRootNode || node.expanded || deep === true) {
							// Create a UL to hold the children
							if (!node.ul) {
								node.ul = document.createElement("ul");
								if (
									(collapsed === true && !_recursive) ||
									!node.expanded
								) {
									// hide top UL, so we can use an animation to show it later
									node.ul.style.display = "none";
								}
								if (aria) {
									$(node.ul).attr("role", "group");
								}
								if (node.li) {
									// issue #67
									node.li.appendChild(node.ul);
								} else {
									node.tree.$div.append(node.ul);
								}
							}
							// Add child markup
							for (i = 0, l = children.length; i < l; i++) {
								subCtx = $.extend({}, ctx, { node: children[i] });
								this.nodeRender(subCtx, force, deep, false, true);
							}
							// Remove <li> if nodes have moved to another parent
							childLI = node.ul.firstChild;
							while (childLI) {
								childNode2 = childLI.ftnode;
								if (childNode2 && childNode2.parent !== node) {
									node.debug(
										"_fixParent: remove missing " + childNode2,
										childLI
									);
									next = childLI.nextSibling;
									childLI.parentNode.removeChild(childLI);
									childLI = next;
								} else {
									childLI = childLI.nextSibling;
								}
							}
							// Make sure, that <li> order matches node.children order.
							childLI = node.ul.firstChild;
							for (i = 0, l = children.length - 1; i < l; i++) {
								childNode1 = children[i];
								childNode2 = childLI.ftnode;
								if (childNode1 === childNode2) {
									childLI = childLI.nextSibling;
								} else {
									// node.debug("_fixOrder: mismatch at index " + i + ": " + childNode1 + " != " + childNode2);
									node.ul.insertBefore(
										childNode1.li,
										childNode2.li
									);
								}
							}
						}
					} else {
						// No children: remove markup if any
						if (node.ul) {
							// alert("remove child markup for " + node);
							this.warn("remove child markup for " + node);
							this.nodeRemoveChildMarkup(ctx);
						}
					}
					if (!isRootNode) {
						// Update element classes according to node state
						// this.nodeRenderStatus(ctx);
						// Finally add the whole structure to the DOM, so the browser can render
						if (firstTime) {
							// #486: successorLi is set, if we re-rendered (i.e. discarded)
							// existing markup, which  we want to insert at the same position.
							// (null is equivalent to append)
							// 		parent.ul.appendChild(node.li);
							parent.ul.insertBefore(node.li, successorLi);
						}
					}
				},
				/** Create HTML inside the node's outer `<span>` (i.e. expander, checkbox,
				 * icon, and title).
				 *
				 * nodeRenderStatus() is implied.
				 * @param {EventData} ctx
				 * @param {string} [title] optinal new title
				 */
				nodeRenderTitle: function (ctx, title) {
					// set node connector images, links and text
					var checkbox,
						className,
						icon,
						nodeTitle,
						role,
						tabindex,
						tooltip,
						iconTooltip,
						node = ctx.node,
						tree = ctx.tree,
						opts = ctx.options,
						aria = opts.aria,
						level = node.getLevel(),
						ares = [];

					if (title !== undefined) {
						node.title = title;
					}
					if (!node.span || tree._enableUpdate === false) {
						// Silently bail out if node was not rendered yet, assuming
						// node.render() will be called as the node becomes visible
						return;
					}
					// Connector (expanded, expandable or simple)
					role =
						aria && node.hasChildren() !== false
							? " role='button'"
							: "";
					if (level < opts.minExpandLevel) {
						if (!node.lazy) {
							node.expanded = true;
						}
						if (level > 1) {
							ares.push(
								"<span " +
									role +
									" class='fancytree-expander fancytree-expander-fixed'></span>"
							);
						}
						// .. else (i.e. for root level) skip expander/connector alltogether
					} else {
						ares.push(
							"<span " + role + " class='fancytree-expander'></span>"
						);
					}
					// Checkbox mode
					checkbox = FT.evalOption("checkbox", node, node, opts, false);

					if (checkbox && !node.isStatusNode()) {
						role = aria ? " role='checkbox'" : "";
						className = "fancytree-checkbox";
						if (
							checkbox === "radio" ||
							(node.parent && node.parent.radiogroup)
						) {
							className += " fancytree-radio";
						}
						ares.push(
							"<span " + role + " class='" + className + "'></span>"
						);
					}
					// Folder or doctype icon
					if (node.data.iconClass !== undefined) {
						// 2015-11-16
						// Handle / warn about backward compatibility
						if (node.icon) {
							$.error(
								"'iconClass' node option is deprecated since v2.14.0: use 'icon' only instead"
							);
						} else {
							node.warn(
								"'iconClass' node option is deprecated since v2.14.0: use 'icon' instead"
							);
							node.icon = node.data.iconClass;
						}
					}
					// If opts.icon is a callback and returns something other than undefined, use that
					// else if node.icon is a boolean or string, use that
					// else if opts.icon is a boolean or string, use that
					// else show standard icon (which may be different for folders or documents)
					icon = FT.evalOption("icon", node, node, opts, true);
					// if( typeof icon !== "boolean" ) {
					// 	// icon is defined, but not true/false: must be a string
					// 	icon = "" + icon;
					// }
					if (icon !== false) {
						role = aria ? " role='presentation'" : "";

						iconTooltip = FT.evalOption(
							"iconTooltip",
							node,
							node,
							opts,
							null
						);
						iconTooltip = iconTooltip
							? " title='" + _escapeTooltip(iconTooltip) + "'"
							: "";

						if (typeof icon === "string") {
							if (TEST_IMG.test(icon)) {
								// node.icon is an image url. Prepend imagePath
								icon =
									icon.charAt(0) === "/"
										? icon
										: (opts.imagePath || "") + icon;
								ares.push(
									"<img src='" +
										icon +
										"' class='fancytree-icon'" +
										iconTooltip +
										" alt='' />"
								);
							} else {
								ares.push(
									"<span " +
										role +
										" class='fancytree-custom-icon " +
										icon +
										"'" +
										iconTooltip +
										"></span>"
								);
							}
						} else if (icon.text) {
							ares.push(
								"<span " +
									role +
									" class='fancytree-custom-icon " +
									(icon.addClass || "") +
									"'" +
									iconTooltip +
									">" +
									FT.escapeHtml(icon.text) +
									"</span>"
							);
						} else if (icon.html) {
							ares.push(
								"<span " +
									role +
									" class='fancytree-custom-icon " +
									(icon.addClass || "") +
									"'" +
									iconTooltip +
									">" +
									icon.html +
									"</span>"
							);
						} else {
							// standard icon: theme css will take care of this
							ares.push(
								"<span " +
									role +
									" class='fancytree-icon'" +
									iconTooltip +
									"></span>"
							);
						}
					}
					// Node title
					nodeTitle = "";
					if (opts.renderTitle) {
						nodeTitle =
							opts.renderTitle.call(
								tree,
								{ type: "renderTitle" },
								ctx
							) || "";
					}
					if (!nodeTitle) {
						tooltip = FT.evalOption("tooltip", node, node, opts, null);
						if (tooltip === true) {
							tooltip = node.title;
						}
						// if( node.tooltip ) {
						// 	tooltip = node.tooltip;
						// } else if ( opts.tooltip ) {
						// 	tooltip = opts.tooltip === true ? node.title : opts.tooltip.call(tree, node);
						// }
						tooltip = tooltip
							? " title='" + _escapeTooltip(tooltip) + "'"
							: "";
						tabindex = opts.titlesTabbable ? " tabindex='0'" : "";

						nodeTitle =
							"<span class='fancytree-title'" +
							tooltip +
							tabindex +
							">" +
							(opts.escapeTitles
								? FT.escapeHtml(node.title)
								: node.title) +
							"</span>";
					}
					ares.push(nodeTitle);
					// Note: this will trigger focusout, if node had the focus
					//$(node.span).html(ares.join("")); // it will cleanup the jQuery data currently associated with SPAN (if any), but it executes more slowly
					node.span.innerHTML = ares.join("");
					// Update CSS classes
					this.nodeRenderStatus(ctx);
					if (opts.enhanceTitle) {
						ctx.$title = $(">span.fancytree-title", node.span);
						nodeTitle =
							opts.enhanceTitle.call(
								tree,
								{ type: "enhanceTitle" },
								ctx
							) || "";
					}
				},
				/** Update element classes according to node state.
				 * @param {EventData} ctx
				 */
				nodeRenderStatus: function (ctx) {
					// Set classes for current status
					var $ariaElem,
						node = ctx.node,
						tree = ctx.tree,
						opts = ctx.options,
						// 	nodeContainer = node[tree.nodeContainerAttrName],
						hasChildren = node.hasChildren(),
						isLastSib = node.isLastSibling(),
						aria = opts.aria,
						cn = opts._classNames,
						cnList = [],
						statusElem = node[tree.statusClassPropName];

					if (!statusElem || tree._enableUpdate === false) {
						// if this function is called for an unrendered node, ignore it (will be updated on nect render anyway)
						return;
					}
					if (aria) {
						$ariaElem = $(node.tr || node.li);
					}
					// Build a list of class names that we will add to the node <span>
					cnList.push(cn.node);
					if (tree.activeNode === node) {
						cnList.push(cn.active);
						// 		$(">span.fancytree-title", statusElem).attr("tabindex", "0");
						// 		tree.$container.removeAttr("tabindex");
						// }else{
						// 		$(">span.fancytree-title", statusElem).removeAttr("tabindex");
						// 		tree.$container.attr("tabindex", "0");
					}
					if (tree.focusNode === node) {
						cnList.push(cn.focused);
					}
					if (node.expanded) {
						cnList.push(cn.expanded);
					}
					if (aria) {
						if (hasChildren === false) {
							$ariaElem.removeAttr("aria-expanded");
						} else {
							$ariaElem.attr("aria-expanded", Boolean(node.expanded));
						}
					}
					if (node.folder) {
						cnList.push(cn.folder);
					}
					if (hasChildren !== false) {
						cnList.push(cn.hasChildren);
					}
					// TODO: required?
					if (isLastSib) {
						cnList.push(cn.lastsib);
					}
					if (node.lazy && node.children == null) {
						cnList.push(cn.lazy);
					}
					if (node.partload) {
						cnList.push(cn.partload);
					}
					if (node.partsel) {
						cnList.push(cn.partsel);
					}
					if (FT.evalOption("unselectable", node, node, opts, false)) {
						cnList.push(cn.unselectable);
					}
					if (node._isLoading) {
						cnList.push(cn.loading);
					}
					if (node._error) {
						cnList.push(cn.error);
					}
					if (node.statusNodeType) {
						cnList.push(cn.statusNodePrefix + node.statusNodeType);
					}
					if (node.selected) {
						cnList.push(cn.selected);
						if (aria) {
							$ariaElem.attr("aria-selected", true);
						}
					} else if (aria) {
						$ariaElem.attr("aria-selected", false);
					}
					if (node.extraClasses) {
						cnList.push(node.extraClasses);
					}
					// IE6 doesn't correctly evaluate multiple class names,
					// so we create combined class names that can be used in the CSS
					if (hasChildren === false) {
						cnList.push(
							cn.combinedExpanderPrefix + "n" + (isLastSib ? "l" : "")
						);
					} else {
						cnList.push(
							cn.combinedExpanderPrefix +
								(node.expanded ? "e" : "c") +
								(node.lazy && node.children == null ? "d" : "") +
								(isLastSib ? "l" : "")
						);
					}
					cnList.push(
						cn.combinedIconPrefix +
							(node.expanded ? "e" : "c") +
							(node.folder ? "f" : "")
					);
					// node.span.className = cnList.join(" ");
					statusElem.className = cnList.join(" ");

					// TODO: we should not set this in the <span> tag also, if we set it here:
					// Maybe most (all) of the classes should be set in LI instead of SPAN?
					if (node.li) {
						// #719: we have to consider that there may be already other classes:
						$(node.li).toggleClass(cn.lastsib, isLastSib);
					}
				},
				/** Activate node.
				 * flag defaults to true.
				 * If flag is true, the node is activated (must be a synchronous operation)
				 * If flag is false, the node is deactivated (must be a synchronous operation)
				 * @param {EventData} ctx
				 * @param {boolean} [flag=true]
				 * @param {object} [opts] additional options. Defaults to {noEvents: false, noFocus: false}
				 * @returns {$.Promise}
				 */
				nodeSetActive: function (ctx, flag, callOpts) {
					// Handle user click / [space] / [enter], according to clickFolderMode.
					callOpts = callOpts || {};
					var subCtx,
						node = ctx.node,
						tree = ctx.tree,
						opts = ctx.options,
						noEvents = callOpts.noEvents === true,
						noFocus = callOpts.noFocus === true,
						scroll = callOpts.scrollIntoView !== false,
						isActive = node === tree.activeNode;

					// flag defaults to true
					flag = flag !== false;
					// node.debug("nodeSetActive", flag);

					if (isActive === flag) {
						// Nothing to do
						return _getResolvedPromise(node);
					}
					// #1042: don't scroll between mousedown/-up when clicking an embedded link
					if (
						scroll &&
						ctx.originalEvent &&
						$(ctx.originalEvent.target).is("a,:checkbox")
					) {
						node.info("Not scrolling while clicking an embedded link.");
						scroll = false;
					}
					if (
						flag &&
						!noEvents &&
						this._triggerNodeEvent(
							"beforeActivate",
							node,
							ctx.originalEvent
						) === false
					) {
						// Callback returned false
						return _getRejectedPromise(node, ["rejected"]);
					}
					if (flag) {
						if (tree.activeNode) {
							_assert(
								tree.activeNode !== node,
								"node was active (inconsistency)"
							);
							subCtx = $.extend({}, ctx, { node: tree.activeNode });
							tree.nodeSetActive(subCtx, false);
							_assert(
								tree.activeNode === null,
								"deactivate was out of sync?"
							);
						}

						if (opts.activeVisible) {
							// If no focus is set (noFocus: true) and there is no focused node, this node is made visible.
							// scroll = noFocus && tree.focusNode == null;
							// #863: scroll by default (unless `scrollIntoView: false` was passed)
							node.makeVisible({ scrollIntoView: scroll });
						}
						tree.activeNode = node;
						tree.nodeRenderStatus(ctx);
						if (!noFocus) {
							tree.nodeSetFocus(ctx);
						}
						if (!noEvents) {
							tree._triggerNodeEvent(
								"activate",
								node,
								ctx.originalEvent
							);
						}
					} else {
						_assert(
							tree.activeNode === node,
							"node was not active (inconsistency)"
						);
						tree.activeNode = null;
						this.nodeRenderStatus(ctx);
						if (!noEvents) {
							ctx.tree._triggerNodeEvent(
								"deactivate",
								node,
								ctx.originalEvent
							);
						}
					}
					return _getResolvedPromise(node);
				},
				/** Expand or collapse node, return Deferred.promise.
				 *
				 * @param {EventData} ctx
				 * @param {boolean} [flag=true]
				 * @param {object} [opts] additional options. Defaults to `{noAnimation: false, noEvents: false}`
				 * @returns {$.Promise} The deferred will be resolved as soon as the (lazy)
				 *     data was retrieved, rendered, and the expand animation finished.
				 */
				nodeSetExpanded: function (ctx, flag, callOpts) {
					callOpts = callOpts || {};
					var _afterLoad,
						dfd,
						i,
						l,
						parents,
						prevAC,
						node = ctx.node,
						tree = ctx.tree,
						opts = ctx.options,
						noAnimation = callOpts.noAnimation === true,
						noEvents = callOpts.noEvents === true;

					// flag defaults to true
					flag = flag !== false;

					// node.debug("nodeSetExpanded(" + flag + ")");

					if ($(node.li).hasClass(opts._classNames.animating)) {
						node.warn(
							"setExpanded(" + flag + ") while animating: ignored."
						);
						return _getRejectedPromise(node, ["recursion"]);
					}

					if ((node.expanded && flag) || (!node.expanded && !flag)) {
						// Nothing to do
						// node.debug("nodeSetExpanded(" + flag + "): nothing to do");
						return _getResolvedPromise(node);
					} else if (flag && !node.lazy && !node.hasChildren()) {
						// Prevent expanding of empty nodes
						// return _getRejectedPromise(node, ["empty"]);
						return _getResolvedPromise(node);
					} else if (!flag && node.getLevel() < opts.minExpandLevel) {
						// Prevent collapsing locked levels
						return _getRejectedPromise(node, ["locked"]);
					} else if (
						!noEvents &&
						this._triggerNodeEvent(
							"beforeExpand",
							node,
							ctx.originalEvent
						) === false
					) {
						// Callback returned false
						return _getRejectedPromise(node, ["rejected"]);
					}
					// If this node inside a collpased node, no animation and scrolling is needed
					if (!noAnimation && !node.isVisible()) {
						noAnimation = callOpts.noAnimation = true;
					}

					dfd = new $.Deferred();

					// Auto-collapse mode: collapse all siblings
					if (flag && !node.expanded && opts.autoCollapse) {
						parents = node.getParentList(false, true);
						prevAC = opts.autoCollapse;
						try {
							opts.autoCollapse = false;
							for (i = 0, l = parents.length; i < l; i++) {
								// TODO: should return promise?
								this._callHook(
									"nodeCollapseSiblings",
									parents[i],
									callOpts
								);
							}
						} finally {
							opts.autoCollapse = prevAC;
						}
					}
					// Trigger expand/collapse after expanding
					dfd.done(function () {
						var lastChild = node.getLastChild();

						if (
							flag &&
							opts.autoScroll &&
							!noAnimation &&
							lastChild &&
							tree._enableUpdate
						) {
							// Scroll down to last child, but keep current node visible
							lastChild
								.scrollIntoView(true, { topNode: node })
								.always(function () {
									if (!noEvents) {
										ctx.tree._triggerNodeEvent(
											flag ? "expand" : "collapse",
											ctx
										);
									}
								});
						} else {
							if (!noEvents) {
								ctx.tree._triggerNodeEvent(
									flag ? "expand" : "collapse",
									ctx
								);
							}
						}
					});
					// vvv Code below is executed after loading finished:
					_afterLoad = function (callback) {
						var cn = opts._classNames,
							isVisible,
							isExpanded,
							effect = opts.toggleEffect;

						node.expanded = flag;
						tree._callHook(
							"treeStructureChanged",
							ctx,
							flag ? "expand" : "collapse"
						);
						// Create required markup, but make sure the top UL is hidden, so we
						// can animate later
						tree._callHook("nodeRender", ctx, false, false, true);

						// Hide children, if node is collapsed
						if (node.ul) {
							isVisible = node.ul.style.display !== "none";
							isExpanded = !!node.expanded;
							if (isVisible === isExpanded) {
								node.warn(
									"nodeSetExpanded: UL.style.display already set"
								);
							} else if (!effect || noAnimation) {
								node.ul.style.display =
									node.expanded || !parent ? "" : "none";
							} else {
								// The UI toggle() effect works with the ext-wide extension,
								// while jQuery.animate() has problems when the title span
								// has position: absolute.
								// Since jQuery UI 1.12, the blind effect requires the parent
								// element to have 'position: relative'.
								// See #716, #717
								$(node.li).addClass(cn.animating); // #717

								if (_isFunction($(node.ul)[effect.effect])) {
									// tree.debug( "use jquery." + effect.effect + " method" );
									$(node.ul)[effect.effect]({
										duration: effect.duration,
										always: function () {
											// node.debug("fancytree-animating end: " + node.li.className);
											$(this).removeClass(cn.animating); // #716
											$(node.li).removeClass(cn.animating); // #717
											callback();
										},
									});
								} else {
									// The UI toggle() effect works with the ext-wide extension,
									// while jQuery.animate() has problems when the title span
									// has positon: absolute.
									// Since jQuery UI 1.12, the blind effect requires the parent
									// element to have 'position: relative'.
									// See #716, #717
									// tree.debug("use specified effect (" + effect.effect + ") with the jqueryui.toggle method");

									// try to stop an animation that might be already in progress
									$(node.ul).stop(true, true); //< does not work after resetLazy has been called for a node whose animation wasn't complete and effect was "blind"

									// dirty fix to remove a defunct animation (effect: "blind") after resetLazy has been called
									$(node.ul)
										.parent()
										.find(".ui-effects-placeholder")
										.remove();

									$(node.ul).toggle(
										effect.effect,
										effect.options,
										effect.duration,
										function () {
											// node.debug("fancytree-animating end: " + node.li.className);
											$(this).removeClass(cn.animating); // #716
											$(node.li).removeClass(cn.animating); // #717
											callback();
										}
									);
								}
								return;
							}
						}
						callback();
					};
					// ^^^ Code above is executed after loading finshed.

					// Load lazy nodes, if any. Then continue with _afterLoad()
					if (flag && node.lazy && node.hasChildren() === undefined) {
						// node.debug("nodeSetExpanded: load start...");
						node.load()
							.done(function () {
								// node.debug("nodeSetExpanded: load done");
								if (dfd.notifyWith) {
									// requires jQuery 1.6+
									dfd.notifyWith(node, ["loaded"]);
								}
								_afterLoad(function () {
									dfd.resolveWith(node);
								});
							})
							.fail(function (errMsg) {
								_afterLoad(function () {
									dfd.rejectWith(node, [
										"load failed (" + errMsg + ")",
									]);
								});
							});
						/*
						var source = tree._triggerNodeEvent("lazyLoad", node, ctx.originalEvent);
						_assert(typeof source !== "boolean", "lazyLoad event must return source in data.result");
						node.debug("nodeSetExpanded: load start...");
						this._callHook("nodeLoadChildren", ctx, source).done(function(){
							node.debug("nodeSetExpanded: load done");
							if(dfd.notifyWith){ // requires jQuery 1.6+
								dfd.notifyWith(node, ["loaded"]);
							}
							_afterLoad.call(tree);
						}).fail(function(errMsg){
							dfd.rejectWith(node, ["load failed (" + errMsg + ")"]);
						});
						*/
					} else {
						_afterLoad(function () {
							dfd.resolveWith(node);
						});
					}
					// node.debug("nodeSetExpanded: returns");
					return dfd.promise();
				},
				/** Focus or blur this node.
				 * @param {EventData} ctx
				 * @param {boolean} [flag=true]
				 */
				nodeSetFocus: function (ctx, flag) {
					// ctx.node.debug("nodeSetFocus(" + flag + ")");
					var ctx2,
						tree = ctx.tree,
						node = ctx.node,
						opts = tree.options,
						// et = ctx.originalEvent && ctx.originalEvent.type,
						isInput = ctx.originalEvent
							? $(ctx.originalEvent.target).is(":input")
							: false;

					flag = flag !== false;

					// (node || tree).debug("nodeSetFocus(" + flag + "), event: " + et + ", isInput: "+ isInput);
					// Blur previous node if any
					if (tree.focusNode) {
						if (tree.focusNode === node && flag) {
							// node.debug("nodeSetFocus(" + flag + "): nothing to do");
							return;
						}
						ctx2 = $.extend({}, ctx, { node: tree.focusNode });
						tree.focusNode = null;
						this._triggerNodeEvent("blur", ctx2);
						this._callHook("nodeRenderStatus", ctx2);
					}
					// Set focus to container and node
					if (flag) {
						if (!this.hasFocus()) {
							node.debug("nodeSetFocus: forcing container focus");
							this._callHook("treeSetFocus", ctx, true, {
								calledByNode: true,
							});
						}
						node.makeVisible({ scrollIntoView: false });
						tree.focusNode = node;
						if (opts.titlesTabbable) {
							if (!isInput) {
								// #621
								$(node.span).find(".fancytree-title").focus();
							}
						}
						if (opts.aria) {
							// Set active descendant to node's span ID (create one, if needed)
							$(tree.$container).attr(
								"aria-activedescendant",
								$(node.tr || node.li)
									.uniqueId()
									.attr("id")
							);
							// "ftal_" + opts.idPrefix + node.key);
						}
						// $(node.span).find(".fancytree-title").focus();
						this._triggerNodeEvent("focus", ctx);

						// determine if we have focus on or inside tree container
						var hasFancytreeFocus =
							document.activeElement === tree.$container.get(0) ||
							$(document.activeElement, tree.$container).length >= 1;

						if (!hasFancytreeFocus) {
							// We cannot set KB focus to a node, so use the tree container
							// #563, #570: IE scrolls on every call to .focus(), if the container
							// is partially outside the viewport. So do it only, when absolutely
							// necessary.
							$(tree.$container).focus();
						}

						// if( opts.autoActivate ){
						// 	tree.nodeSetActive(ctx, true);
						// }
						if (opts.autoScroll) {
							node.scrollIntoView();
						}
						this._callHook("nodeRenderStatus", ctx);
					}
				},
				/** (De)Select node, return new status (sync).
				 *
				 * @param {EventData} ctx
				 * @param {boolean} [flag=true]
				 * @param {object} [opts] additional options. Defaults to {noEvents: false,
				 *     propagateDown: null, propagateUp: null,
				 *     callback: null,
				 *     }
				 * @returns {boolean} previous status
				 */
				nodeSetSelected: function (ctx, flag, callOpts) {
					callOpts = callOpts || {};
					var node = ctx.node,
						tree = ctx.tree,
						opts = ctx.options,
						noEvents = callOpts.noEvents === true,
						parent = node.parent;

					// flag defaults to true
					flag = flag !== false;

					// node.debug("nodeSetSelected(" + flag + ")", ctx);

					// Cannot (de)select unselectable nodes directly (only by propagation or
					// by setting the `.selected` property)
					if (FT.evalOption("unselectable", node, node, opts, false)) {
						return;
					}

					// Remember the user's intent, in case down -> up propagation prevents
					// applying it to node.selected
					node._lastSelectIntent = flag; // Confusing use of '!'

					// Nothing to do?
					if (!!node.selected === flag) {
						if (opts.selectMode === 3 && node.partsel && !flag) {
							// If propagation prevented selecting this node last time, we still
							// want to allow to apply setSelected(false) now
						} else {
							return flag;
						}
					}

					if (
						!noEvents &&
						this._triggerNodeEvent(
							"beforeSelect",
							node,
							ctx.originalEvent
						) === false
					) {
						return !!node.selected;
					}
					if (flag && opts.selectMode === 1) {
						// single selection mode (we don't uncheck all tree nodes, for performance reasons)
						if (tree.lastSelectedNode) {
							tree.lastSelectedNode.setSelected(false);
						}
						node.selected = flag;
					} else if (
						opts.selectMode === 3 &&
						parent &&
						!parent.radiogroup &&
						!node.radiogroup
					) {
						// multi-hierarchical selection mode
						node.selected = flag;
						node.fixSelection3AfterClick(callOpts);
					} else if (parent && parent.radiogroup) {
						node.visitSiblings(function (n) {
							n._changeSelectStatusAttrs(flag && n === node);
						}, true);
					} else {
						// default: selectMode: 2, multi selection mode
						node.selected = flag;
					}
					this.nodeRenderStatus(ctx);
					tree.lastSelectedNode = flag ? node : null;
					if (!noEvents) {
						tree._triggerNodeEvent("select", ctx);
					}
				},
				/** Show node status (ok, loading, error, nodata) using styles and a dummy child node.
				 *
				 * @param {EventData} ctx
				 * @param status
				 * @param message
				 * @param details
				 * @since 2.3
				 */
				nodeSetStatus: function (ctx, status, message, details) {
					var node = ctx.node,
						tree = ctx.tree;

					function _clearStatusNode() {
						// Remove dedicated dummy node, if any
						var firstChild = node.children ? node.children[0] : null;
						if (firstChild && firstChild.isStatusNode()) {
							try {
								// I've seen exceptions here with loadKeyPath...
								if (node.ul) {
									node.ul.removeChild(firstChild.li);
									firstChild.li = null; // avoid leaks (DT issue 215)
								}
							} catch (e) {}
							if (node.children.length === 1) {
								node.children = [];
							} else {
								node.children.shift();
							}
							tree._callHook(
								"treeStructureChanged",
								ctx,
								"clearStatusNode"
							);
						}
					}
					function _setStatusNode(data, type) {
						// Create/modify the dedicated dummy node for 'loading...' or
						// 'error!' status. (only called for direct child of the invisible
						// system root)
						var firstChild = node.children ? node.children[0] : null;
						if (firstChild && firstChild.isStatusNode()) {
							$.extend(firstChild, data);
							firstChild.statusNodeType = type;
							tree._callHook("nodeRenderTitle", firstChild);
						} else {
							node._setChildren([data]);
							tree._callHook(
								"treeStructureChanged",
								ctx,
								"setStatusNode"
							);
							node.children[0].statusNodeType = type;
							tree.render();
						}
						return node.children[0];
					}

					switch (status) {
						case "ok":
							_clearStatusNode();
							node._isLoading = false;
							node._error = null;
							node.renderStatus();
							break;
						case "loading":
							if (!node.parent) {
								_setStatusNode(
									{
										title:
											tree.options.strings.loading +
											(message ? " (" + message + ")" : ""),
										// icon: true,  // needed for 'loding' icon
										checkbox: false,
										tooltip: details,
									},
									status
								);
							}
							node._isLoading = true;
							node._error = null;
							node.renderStatus();
							break;
						case "error":
							_setStatusNode(
								{
									title:
										tree.options.strings.loadError +
										(message ? " (" + message + ")" : ""),
									// icon: false,
									checkbox: false,
									tooltip: details,
								},
								status
							);
							node._isLoading = false;
							node._error = { message: message, details: details };
							node.renderStatus();
							break;
						case "nodata":
							_setStatusNode(
								{
									title: message || tree.options.strings.noData,
									// icon: false,
									checkbox: false,
									tooltip: details,
								},
								status
							);
							node._isLoading = false;
							node._error = null;
							node.renderStatus();
							break;
						default:
							$.error("invalid node status " + status);
					}
				},
				/**
				 *
				 * @param {EventData} ctx
				 */
				nodeToggleExpanded: function (ctx) {
					return this.nodeSetExpanded(ctx, !ctx.node.expanded);
				},
				/**
				 * @param {EventData} ctx
				 */
				nodeToggleSelected: function (ctx) {
					var node = ctx.node,
						flag = !node.selected;

					// In selectMode: 3 this node may be unselected+partsel, even if
					// setSelected(true) was called before, due to `unselectable` children.
					// In this case, we now toggle as `setSelected(false)`
					if (
						node.partsel &&
						!node.selected &&
						node._lastSelectIntent === true
					) {
						flag = false;
						node.selected = true; // so it is not considered 'nothing to do'
					}
					node._lastSelectIntent = flag;
					return this.nodeSetSelected(ctx, flag);
				},
				/** Remove all nodes.
				 * @param {EventData} ctx
				 */
				treeClear: function (ctx) {
					var tree = ctx.tree;
					tree.activeNode = null;
					tree.focusNode = null;
					tree.$div.find(">ul.fancytree-container").empty();
					// TODO: call destructors and remove reference loops
					tree.rootNode.children = null;
					tree._callHook("treeStructureChanged", ctx, "clear");
				},
				/** Widget was created (called only once, even it re-initialized).
				 * @param {EventData} ctx
				 */
				treeCreate: function (ctx) {},
				/** Widget was destroyed.
				 * @param {EventData} ctx
				 */
				treeDestroy: function (ctx) {
					this.$div.find(">ul.fancytree-container").remove();
					if (this.$source) {
						this.$source.removeClass("fancytree-helper-hidden");
					}
				},
				/** Widget was (re-)initialized.
				 * @param {EventData} ctx
				 */
				treeInit: function (ctx) {
					var tree = ctx.tree,
						opts = tree.options;

					//this.debug("Fancytree.treeInit()");
					// Add container to the TAB chain
					// See http://www.w3.org/TR/wai-aria-practices/#focus_activedescendant
					// #577: Allow to set tabindex to "0", "-1" and ""
					tree.$container.attr("tabindex", opts.tabindex);

					// Copy some attributes to tree.data
					$.each(TREE_ATTRS, function (i, attr) {
						if (opts[attr] !== undefined) {
							tree.info("Move option " + attr + " to tree");
							tree[attr] = opts[attr];
							delete opts[attr];
						}
					});

					if (opts.checkboxAutoHide) {
						tree.$container.addClass("fancytree-checkbox-auto-hide");
					}
					if (opts.rtl) {
						tree.$container
							.attr("DIR", "RTL")
							.addClass("fancytree-rtl");
					} else {
						tree.$container
							.removeAttr("DIR")
							.removeClass("fancytree-rtl");
					}
					if (opts.aria) {
						tree.$container.attr("role", "tree");
						if (opts.selectMode !== 1) {
							tree.$container.attr("aria-multiselectable", true);
						}
					}
					this.treeLoad(ctx);
				},
				/** Parse Fancytree from source, as configured in the options.
				 * @param {EventData} ctx
				 * @param {object} [source] optional new source (use last data otherwise)
				 */
				treeLoad: function (ctx, source) {
					var metaData,
						type,
						$ul,
						tree = ctx.tree,
						$container = ctx.widget.element,
						dfd,
						// calling context for root node
						rootCtx = $.extend({}, ctx, { node: this.rootNode });

					if (tree.rootNode.children) {
						this.treeClear(ctx);
					}
					source = source || this.options.source;

					if (!source) {
						type = $container.data("type") || "html";
						switch (type) {
							case "html":
								// There should be an embedded `<ul>` with initial nodes,
								// but another `<ul class='fancytree-container'>` is appended
								// to the tree's <div> on startup anyway.
								$ul = $container
									.find(">ul")
									.not(".fancytree-container")
									.first();

								if ($ul.length) {
									$ul.addClass(
										"ui-fancytree-source fancytree-helper-hidden"
									);
									source = $.ui.fancytree.parseHtml($ul);
									// allow to init tree.data.foo from <ul data-foo=''>
									this.data = $.extend(
										this.data,
										_getElementDataAsDict($ul)
									);
								} else {
									FT.warn(
										"No `source` option was passed and container does not contain `<ul>`: assuming `source: []`."
									);
									source = [];
								}
								break;
							case "json":
								source = $.parseJSON($container.text());
								// $container already contains the <ul>, but we remove the plain (json) text
								// $container.empty();
								$container
									.contents()
									.filter(function () {
										return this.nodeType === 3;
									})
									.remove();
								if ($.isPlainObject(source)) {
									// We got {foo: 'abc', children: [...]}
									_assert(
										_isArray(source.children),
										"if an object is passed as source, it must contain a 'children' array (all other properties are added to 'tree.data')"
									);
									metaData = source;
									source = source.children;
									delete metaData.children;
									// Copy some attributes to tree.data
									$.each(TREE_ATTRS, function (i, attr) {
										if (metaData[attr] !== undefined) {
											tree[attr] = metaData[attr];
											delete metaData[attr];
										}
									});
									// Copy extra properties to tree.data.foo
									$.extend(tree.data, metaData);
								}
								break;
							default:
								$.error("Invalid data-type: " + type);
						}
					} else if (typeof source === "string") {
						// TODO: source is an element ID
						$.error("Not implemented");
					}

					// preInit is fired when the widget markup is created, but nodes
					// not yet loaded
					tree._triggerTreeEvent("preInit", null);

					// Trigger fancytreeinit after nodes have been loaded
					dfd = this.nodeLoadChildren(rootCtx, source)
						.done(function () {
							tree._callHook(
								"treeStructureChanged",
								ctx,
								"loadChildren"
							);
							tree.render();
							if (ctx.options.selectMode === 3) {
								tree.rootNode.fixSelection3FromEndNodes();
							}
							if (tree.activeNode && tree.options.activeVisible) {
								tree.activeNode.makeVisible();
							}
							tree._triggerTreeEvent("init", null, { status: true });
						})
						.fail(function () {
							tree.render();
							tree._triggerTreeEvent("init", null, { status: false });
						});
					return dfd;
				},
				/** Node was inserted into or removed from the tree.
				 * @param {EventData} ctx
				 * @param {boolean} add
				 * @param {FancytreeNode} node
				 */
				treeRegisterNode: function (ctx, add, node) {
					ctx.tree._callHook(
						"treeStructureChanged",
						ctx,
						add ? "addNode" : "removeNode"
					);
				},
				/** Widget got focus.
				 * @param {EventData} ctx
				 * @param {boolean} [flag=true]
				 */
				treeSetFocus: function (ctx, flag, callOpts) {
					var targetNode;

					flag = flag !== false;

					// this.debug("treeSetFocus(" + flag + "), callOpts: ", callOpts, this.hasFocus());
					// this.debug("    focusNode: " + this.focusNode);
					// this.debug("    activeNode: " + this.activeNode);
					if (flag !== this.hasFocus()) {
						this._hasFocus = flag;
						if (!flag && this.focusNode) {
							// Node also looses focus if widget blurs
							this.focusNode.setFocus(false);
						} else if (flag && (!callOpts || !callOpts.calledByNode)) {
							$(this.$container).focus();
						}
						this.$container.toggleClass("fancytree-treefocus", flag);
						this._triggerTreeEvent(flag ? "focusTree" : "blurTree");
						if (flag && !this.activeNode) {
							// #712: Use last mousedowned node ('click' event fires after focusin)
							targetNode =
								this._lastMousedownNode || this.getFirstChild();
							if (targetNode) {
								targetNode.setFocus();
							}
						}
					}
				},
				/** Widget option was set using `$().fancytree("option", "KEY", VALUE)`.
				 *
				 * Note: `key` may reference a nested option, e.g. 'dnd5.scroll'.
				 * In this case `value`contains the complete, modified `dnd5` option hash.
				 * We can check for changed values like
				 *     if( value.scroll !== tree.options.dnd5.scroll ) {...}
				 *
				 * @param {EventData} ctx
				 * @param {string} key option name
				 * @param {any} value option value
				 */
				treeSetOption: function (ctx, key, value) {
					var tree = ctx.tree,
						callDefault = true,
						callCreate = false,
						callRender = false;

					switch (key) {
						case "aria":
						case "checkbox":
						case "icon":
						case "minExpandLevel":
						case "tabindex":
							// tree._callHook("treeCreate", tree);
							callCreate = true;
							callRender = true;
							break;
						case "checkboxAutoHide":
							tree.$container.toggleClass(
								"fancytree-checkbox-auto-hide",
								!!value
							);
							break;
						case "escapeTitles":
						case "tooltip":
							callRender = true;
							break;
						case "rtl":
							if (value === false) {
								tree.$container
									.removeAttr("DIR")
									.removeClass("fancytree-rtl");
							} else {
								tree.$container
									.attr("DIR", "RTL")
									.addClass("fancytree-rtl");
							}
							callRender = true;
							break;
						case "source":
							callDefault = false;
							tree._callHook("treeLoad", tree, value);
							callRender = true;
							break;
					}
					tree.debug(
						"set option " +
							key +
							"=" +
							value +
							" <" +
							typeof value +
							">"
					);
					if (callDefault) {
						if (this.widget._super) {
							// jQuery UI 1.9+
							this.widget._super.call(this.widget, key, value);
						} else {
							// jQuery UI <= 1.8, we have to manually invoke the _setOption method from the base widget
							$.Widget.prototype._setOption.call(
								this.widget,
								key,
								value
							);
						}
					}
					if (callCreate) {
						tree._callHook("treeCreate", tree);
					}
					if (callRender) {
						tree.render(true, false); // force, not-deep
					}
				},
				/** A Node was added, removed, moved, or it's visibility changed.
				 * @param {EventData} ctx
				 */
				treeStructureChanged: function (ctx, type) {},
			}
		);

		/*******************************************************************************
		 * jQuery UI widget boilerplate
		 */

		/**
		 * The plugin (derrived from [jQuery.Widget](http://api.jqueryui.com/jQuery.widget/)).
		 *
		 * **Note:**
		 * These methods implement the standard jQuery UI widget API.
		 * It is recommended to use methods of the {Fancytree} instance instead
		 *
		 * @example
		 * // DEPRECATED: Access jQuery UI widget methods and members:
		 * var tree = $("#tree").fancytree("getTree");
		 * var node = $("#tree").fancytree("getActiveNode");
		 *
		 * // RECOMMENDED: Use the Fancytree object API
		 * var tree = $.ui.fancytree.getTree("#tree");
		 * var node = tree.getActiveNode();
		 *
		 * // or you may already have stored the tree instance upon creation:
		 * import {createTree, version} from 'jquery.fancytree'
		 * const tree = createTree('#tree', { ... });
		 * var node = tree.getActiveNode();
		 *
		 * @see {Fancytree_Static#getTree}
		 * @deprecated Use methods of the {Fancytree} instance instead
		 * @mixin Fancytree_Widget
		 */

		$.widget(
			"ui.fancytree",
			/** @lends Fancytree_Widget# */
			{
				/**These options will be used as defaults
				 * @type {FancytreeOptions}
				 */
				options: {
					activeVisible: true,
					ajax: {
						type: "GET",
						cache: false, // false: Append random '_' argument to the request url to prevent caching.
						// timeout: 0, // >0: Make sure we get an ajax error if server is unreachable
						dataType: "json", // Expect json format and pass json object to callbacks.
					},
					aria: true,
					autoActivate: true,
					autoCollapse: false,
					autoScroll: false,
					checkbox: false,
					clickFolderMode: 4,
					copyFunctionsToData: false,
					debugLevel: null, // 0..4 (null: use global setting $.ui.fancytree.debugLevel)
					disabled: false, // TODO: required anymore?
					enableAspx: 42, // TODO: this is truethy, but distinguishable from true: default will change to false in the future
					escapeTitles: false,
					extensions: [],
					focusOnSelect: false,
					generateIds: false,
					icon: true,
					idPrefix: "ft_",
					keyboard: true,
					keyPathSeparator: "/",
					minExpandLevel: 1,
					nodata: true, // (bool, string, or callback) display message, when no data available
					quicksearch: false,
					rtl: false,
					scrollOfs: { top: 0, bottom: 0 },
					scrollParent: null,
					selectMode: 2,
					strings: {
						loading: "Loading...", // &#8230; would be escaped when escapeTitles is true
						loadError: "Load error!",
						moreData: "More...",
						noData: "No data.",
					},
					tabindex: "0",
					titlesTabbable: false,
					toggleEffect: { effect: "slideToggle", duration: 200 }, //< "toggle" or "slideToggle" to use jQuery instead of jQueryUI for toggleEffect animation
					tooltip: false,
					treeId: null,
					_classNames: {
						active: "fancytree-active",
						animating: "fancytree-animating",
						combinedExpanderPrefix: "fancytree-exp-",
						combinedIconPrefix: "fancytree-ico-",
						error: "fancytree-error",
						expanded: "fancytree-expanded",
						focused: "fancytree-focused",
						folder: "fancytree-folder",
						hasChildren: "fancytree-has-children",
						lastsib: "fancytree-lastsib",
						lazy: "fancytree-lazy",
						loading: "fancytree-loading",
						node: "fancytree-node",
						partload: "fancytree-partload",
						partsel: "fancytree-partsel",
						radio: "fancytree-radio",
						selected: "fancytree-selected",
						statusNodePrefix: "fancytree-statusnode-",
						unselectable: "fancytree-unselectable",
					},
					// events
					lazyLoad: null,
					postProcess: null,
				},
				_deprecationWarning: function (name) {
					var tree = this.tree;

					if (tree && tree.options.debugLevel >= 3) {
						tree.warn(
							"$().fancytree('" +
								name +
								"') is deprecated (see https://wwwendt.de/tech/fancytree/doc/jsdoc/Fancytree_Widget.html"
						);
					}
				},
				/* Set up the widget, Called on first $().fancytree() */
				_create: function () {
					this.tree = new Fancytree(this);

					this.$source =
						this.source || this.element.data("type") === "json"
							? this.element
							: this.element.find(">ul").first();
					// Subclass Fancytree instance with all enabled extensions
					var extension,
						extName,
						i,
						opts = this.options,
						extensions = opts.extensions,
						base = this.tree;

					for (i = 0; i < extensions.length; i++) {
						extName = extensions[i];
						extension = $.ui.fancytree._extensions[extName];
						if (!extension) {
							$.error(
								"Could not apply extension '" +
									extName +
									"' (it is not registered, did you forget to include it?)"
							);
						}
						// Add extension options as tree.options.EXTENSION
						// 	_assert(!this.tree.options[extName], "Extension name must not exist as option name: " + extName);

						// console.info("extend " + extName, extension.options, this.tree.options[extName])
						// issue #876: we want to replace custom array-options, not merge them
						this.tree.options[extName] = _simpleDeepMerge(
							{},
							extension.options,
							this.tree.options[extName]
						);
						// this.tree.options[extName] = $.extend(true, {}, extension.options, this.tree.options[extName]);

						// console.info("extend " + extName + " =>", this.tree.options[extName])
						// console.info("extend " + extName + " org default =>", extension.options)

						// Add a namespace tree.ext.EXTENSION, to hold instance data
						_assert(
							this.tree.ext[extName] === undefined,
							"Extension name must not exist as Fancytree.ext attribute: '" +
								extName +
								"'"
						);
						// this.tree[extName] = extension;
						this.tree.ext[extName] = {};
						// Subclass Fancytree methods using proxies.
						_subclassObject(this.tree, base, extension, extName);
						// current extension becomes base for the next extension
						base = extension;
					}
					//
					if (opts.icons !== undefined) {
						// 2015-11-16
						if (opts.icon === true) {
							this.tree.warn(
								"'icons' tree option is deprecated since v2.14.0: use 'icon' instead"
							);
							opts.icon = opts.icons;
						} else {
							$.error(
								"'icons' tree option is deprecated since v2.14.0: use 'icon' only instead"
							);
						}
					}
					if (opts.iconClass !== undefined) {
						// 2015-11-16
						if (opts.icon) {
							$.error(
								"'iconClass' tree option is deprecated since v2.14.0: use 'icon' only instead"
							);
						} else {
							this.tree.warn(
								"'iconClass' tree option is deprecated since v2.14.0: use 'icon' instead"
							);
							opts.icon = opts.iconClass;
						}
					}
					if (opts.tabbable !== undefined) {
						// 2016-04-04
						opts.tabindex = opts.tabbable ? "0" : "-1";
						this.tree.warn(
							"'tabbable' tree option is deprecated since v2.17.0: use 'tabindex='" +
								opts.tabindex +
								"' instead"
						);
					}
					//
					this.tree._callHook("treeCreate", this.tree);
					// Note: 'fancytreecreate' event is fired by widget base class
					//        this.tree._triggerTreeEvent("create");
				},

				/* Called on every $().fancytree() */
				_init: function () {
					this.tree._callHook("treeInit", this.tree);
					// TODO: currently we call bind after treeInit, because treeInit
					// might change tree.$container.
					// It would be better, to move event binding into hooks altogether
					this._bind();
				},

				/* Use the _setOption method to respond to changes to options. */
				_setOption: function (key, value) {
					return this.tree._callHook(
						"treeSetOption",
						this.tree,
						key,
						value
					);
				},

				/** Use the destroy method to clean up any modifications your widget has made to the DOM */
				_destroy: function () {
					this._unbind();
					this.tree._callHook("treeDestroy", this.tree);
					// In jQuery UI 1.8, you must invoke the destroy method from the base widget
					// $.Widget.prototype.destroy.call(this);
					// TODO: delete tree and nodes to make garbage collect easier?
					// TODO: In jQuery UI 1.9 and above, you would define _destroy instead of destroy and not call the base method
				},

				// -------------------------------------------------------------------------

				/* Remove all event handlers for our namespace */
				_unbind: function () {
					var ns = this.tree._ns;
					this.element.off(ns);
					this.tree.$container.off(ns);
					$(document).off(ns);
				},
				/* Add mouse and kyboard handlers to the container */
				_bind: function () {
					var self = this,
						opts = this.options,
						tree = this.tree,
						ns = tree._ns;
					// selstartEvent = ( $.support.selectstart ? "selectstart" : "mousedown" )

					// Remove all previuous handlers for this tree
					this._unbind();

					//alert("keydown" + ns + "foc=" + tree.hasFocus() + tree.$container);
					// tree.debug("bind events; container: ", tree.$container);
					tree.$container
						.on("focusin" + ns + " focusout" + ns, function (event) {
							var node = FT.getNode(event),
								flag = event.type === "focusin";

							if (!flag && node && $(event.target).is("a")) {
								// #764
								node.debug(
									"Ignored focusout on embedded <a> element."
								);
								return;
							}
							// tree.treeOnFocusInOut.call(tree, event);
							// tree.debug("Tree container got event " + event.type, node, event, FT.getEventTarget(event));
							if (flag) {
								if (tree._getExpiringValue("focusin")) {
									// #789: IE 11 may send duplicate focusin events
									tree.debug("Ignored double focusin.");
									return;
								}
								tree._setExpiringValue("focusin", true, 50);

								if (!node) {
									// #789: IE 11 may send focusin before mousdown(?)
									node = tree._getExpiringValue("mouseDownNode");
									if (node) {
										tree.debug(
											"Reconstruct mouse target for focusin from recent event."
										);
									}
								}
							}
							if (node) {
								// For example clicking into an <input> that is part of a node
								tree._callHook(
									"nodeSetFocus",
									tree._makeHookContext(node, event),
									flag
								);
							} else {
								if (
									tree.tbody &&
									$(event.target).parents(
										"table.fancytree-container > thead"
									).length
								) {
									// #767: ignore events in the table's header
									tree.debug(
										"Ignore focus event outside table body.",
										event
									);
								} else {
									tree._callHook("treeSetFocus", tree, flag);
								}
							}
						})
						.on(
							"selectstart" + ns,
							"span.fancytree-title",
							function (event) {
								// prevent mouse-drags to select text ranges
								// tree.debug("<span title> got event " + event.type);
								event.preventDefault();
							}
						)
						.on("keydown" + ns, function (event) {
							// TODO: also bind keyup and keypress
							// tree.debug("got event " + event.type + ", hasFocus:" + tree.hasFocus());
							// if(opts.disabled || opts.keyboard === false || !tree.hasFocus() ){
							if (opts.disabled || opts.keyboard === false) {
								return true;
							}
							var res,
								node = tree.focusNode, // node may be null
								ctx = tree._makeHookContext(node || tree, event),
								prevPhase = tree.phase;

							try {
								tree.phase = "userEvent";
								// If a 'fancytreekeydown' handler returns false, skip the default
								// handling (implemented by tree.nodeKeydown()).
								if (node) {
									res = tree._triggerNodeEvent(
										"keydown",
										node,
										event
									);
								} else {
									res = tree._triggerTreeEvent("keydown", event);
								}
								if (res === "preventNav") {
									res = true; // prevent keyboard navigation, but don't prevent default handling of embedded input controls
								} else if (res !== false) {
									res = tree._callHook("nodeKeydown", ctx);
								}
								return res;
							} finally {
								tree.phase = prevPhase;
							}
						})
						.on("mousedown" + ns, function (event) {
							var et = FT.getEventTarget(event);
							// self.tree.debug("event(" + event.type + "): node: ", et.node);
							// #712: Store the clicked node, so we can use it when we get a focusin event
							//       ('click' event fires after focusin)
							// tree.debug("event(" + event.type + "): node: ", et.node);
							tree._lastMousedownNode = et ? et.node : null;
							// #789: Store the node also for a short period, so we can use it
							// in a *resulting* focusin event
							tree._setExpiringValue(
								"mouseDownNode",
								tree._lastMousedownNode
							);
						})
						.on("click" + ns + " dblclick" + ns, function (event) {
							if (opts.disabled) {
								return true;
							}
							var ctx,
								et = FT.getEventTarget(event),
								node = et.node,
								tree = self.tree,
								prevPhase = tree.phase;

							// self.tree.debug("event(" + event.type + "): node: ", node);
							if (!node) {
								return true; // Allow bubbling of other events
							}
							ctx = tree._makeHookContext(node, event);
							// self.tree.debug("event(" + event.type + "): node: ", node);
							try {
								tree.phase = "userEvent";
								switch (event.type) {
									case "click":
										ctx.targetType = et.type;
										if (node.isPagingNode()) {
											return (
												tree._triggerNodeEvent(
													"clickPaging",
													ctx,
													event
												) === true
											);
										}
										return tree._triggerNodeEvent(
											"click",
											ctx,
											event
										) === false
											? false
											: tree._callHook("nodeClick", ctx);
									case "dblclick":
										ctx.targetType = et.type;
										return tree._triggerNodeEvent(
											"dblclick",
											ctx,
											event
										) === false
											? false
											: tree._callHook("nodeDblclick", ctx);
								}
							} finally {
								tree.phase = prevPhase;
							}
						});
				},
				/** Return the active node or null.
				 * @returns {FancytreeNode}
				 * @deprecated Use methods of the Fancytree instance instead (<a href="Fancytree_Widget.html">example above</a>).
				 */
				getActiveNode: function () {
					this._deprecationWarning("getActiveNode");
					return this.tree.activeNode;
				},
				/** Return the matching node or null.
				 * @param {string} key
				 * @returns {FancytreeNode}
				 * @deprecated Use methods of the Fancytree instance instead (<a href="Fancytree_Widget.html">example above</a>).
				 */
				getNodeByKey: function (key) {
					this._deprecationWarning("getNodeByKey");
					return this.tree.getNodeByKey(key);
				},
				/** Return the invisible system root node.
				 * @returns {FancytreeNode}
				 * @deprecated Use methods of the Fancytree instance instead (<a href="Fancytree_Widget.html">example above</a>).
				 */
				getRootNode: function () {
					this._deprecationWarning("getRootNode");
					return this.tree.rootNode;
				},
				/** Return the current tree instance.
				 * @returns {Fancytree}
				 * @deprecated Use `$.ui.fancytree.getTree()` instead (<a href="Fancytree_Widget.html">example above</a>).
				 */
				getTree: function () {
					this._deprecationWarning("getTree");
					return this.tree;
				},
			}
		);

		// $.ui.fancytree was created by the widget factory. Create a local shortcut:
		FT = $.ui.fancytree;

		/**
		 * Static members in the `$.ui.fancytree` namespace.
		 * This properties and methods can be accessed without instantiating a concrete
		 * Fancytree instance.
		 *
		 * @example
		 * // Access static members:
		 * var node = $.ui.fancytree.getNode(element);
		 * alert($.ui.fancytree.version);
		 *
		 * @mixin Fancytree_Static
		 */
		$.extend(
			$.ui.fancytree,
			/** @lends Fancytree_Static# */
			{
				/** Version number `"MAJOR.MINOR.PATCH"`
				 * @type {string} */
				version: "2.38.3", // Set to semver by 'grunt release'
				/** @type {string}
				 * @description `"production" for release builds` */
				buildType: "production", // Set to 'production' by 'grunt build'
				/** @type {int}
				 * @description 0: silent .. 5: verbose (default: 3 for release builds). */
				debugLevel: 3, // Set to 3 by 'grunt build'
				// Used by $.ui.fancytree.debug() and as default for tree.options.debugLevel

				_nextId: 1,
				_nextNodeKey: 1,
				_extensions: {},
				// focusTree: null,

				/** Expose class object as `$.ui.fancytree._FancytreeClass`.
				 * Useful to extend `$.ui.fancytree._FancytreeClass.prototype`.
				 * @type {Fancytree}
				 */
				_FancytreeClass: Fancytree,
				/** Expose class object as $.ui.fancytree._FancytreeNodeClass
				 * Useful to extend `$.ui.fancytree._FancytreeNodeClass.prototype`.
				 * @type {FancytreeNode}
				 */
				_FancytreeNodeClass: FancytreeNode,
				/* Feature checks to provide backwards compatibility */
				jquerySupports: {
					// http://jqueryui.com/upgrade-guide/1.9/#deprecated-offset-option-merged-into-my-and-at
					positionMyOfs: isVersionAtLeast($.ui.version, 1, 9),
				},
				/** Throw an error if condition fails (debug method).
				 * @param {boolean} cond
				 * @param {string} msg
				 */
				assert: function (cond, msg) {
					return _assert(cond, msg);
				},
				/** Create a new Fancytree instance on a target element.
				 *
				 * @param {Element | jQueryObject | string} el Target DOM element or selector
				 * @param {FancytreeOptions} [opts] Fancytree options
				 * @returns {Fancytree} new tree instance
				 * @example
				 * var tree = $.ui.fancytree.createTree("#tree", {
				 *     source: {url: "my/webservice"}
				 * }); // Create tree for this matching element
				 *
				 * @since 2.25
				 */
				createTree: function (el, opts) {
					var $tree = $(el).fancytree(opts);
					return FT.getTree($tree);
				},
				/** Return a function that executes *fn* at most every *timeout* ms.
				 * @param {integer} timeout
				 * @param {function} fn
				 * @param {boolean} [invokeAsap=false]
				 * @param {any} [ctx]
				 */
				debounce: function (timeout, fn, invokeAsap, ctx) {
					var timer;
					if (arguments.length === 3 && typeof invokeAsap !== "boolean") {
						ctx = invokeAsap;
						invokeAsap = false;
					}
					return function () {
						var args = arguments;
						ctx = ctx || this;
						// eslint-disable-next-line no-unused-expressions
						invokeAsap && !timer && fn.apply(ctx, args);
						clearTimeout(timer);
						timer = setTimeout(function () {
							// eslint-disable-next-line no-unused-expressions
							invokeAsap || fn.apply(ctx, args);
							timer = null;
						}, timeout);
					};
				},
				/** Write message to console if debugLevel >= 4
				 * @param {string} msg
				 */
				debug: function (msg) {
					if ($.ui.fancytree.debugLevel >= 4) {
						consoleApply("log", arguments);
					}
				},
				/** Write error message to console if debugLevel >= 1.
				 * @param {string} msg
				 */
				error: function (msg) {
					if ($.ui.fancytree.debugLevel >= 1) {
						consoleApply("error", arguments);
					}
				},
				/** Convert `<`, `>`, `&`, `"`, `'`, and `/` to the equivalent entities.
				 *
				 * @param {string} s
				 * @returns {string}
				 */
				escapeHtml: function (s) {
					return ("" + s).replace(REX_HTML, function (s) {
						return ENTITY_MAP[s];
					});
				},
				/** Make jQuery.position() arguments backwards compatible, i.e. if
				 * jQuery UI version <= 1.8, convert
				 *   { my: "left+3 center", at: "left bottom", of: $target }
				 * to
				 *   { my: "left center", at: "left bottom", of: $target, offset: "3  0" }
				 *
				 * See http://jqueryui.com/upgrade-guide/1.9/#deprecated-offset-option-merged-into-my-and-at
				 * and http://jsfiddle.net/mar10/6xtu9a4e/
				 *
				 * @param {object} opts
				 * @returns {object} the (potentially modified) original opts hash object
				 */
				fixPositionOptions: function (opts) {
					if (opts.offset || ("" + opts.my + opts.at).indexOf("%") >= 0) {
						$.error(
							"expected new position syntax (but '%' is not supported)"
						);
					}
					if (!$.ui.fancytree.jquerySupports.positionMyOfs) {
						var // parse 'left+3 center' into ['left+3 center', 'left', '+3', 'center', undefined]
							myParts = /(\w+)([+-]?\d+)?\s+(\w+)([+-]?\d+)?/.exec(
								opts.my
							),
							atParts = /(\w+)([+-]?\d+)?\s+(\w+)([+-]?\d+)?/.exec(
								opts.at
							),
							// convert to numbers
							dx =
								(myParts[2] ? +myParts[2] : 0) +
								(atParts[2] ? +atParts[2] : 0),
							dy =
								(myParts[4] ? +myParts[4] : 0) +
								(atParts[4] ? +atParts[4] : 0);

						opts = $.extend({}, opts, {
							// make a copy and overwrite
							my: myParts[1] + " " + myParts[3],
							at: atParts[1] + " " + atParts[3],
						});
						if (dx || dy) {
							opts.offset = "" + dx + " " + dy;
						}
					}
					return opts;
				},
				/** Return a {node: FancytreeNode, type: TYPE} object for a mouse event.
				 *
				 * @param {Event} event Mouse event, e.g. click, ...
				 * @returns {object} Return a {node: FancytreeNode, type: TYPE} object
				 *     TYPE: 'title' | 'prefix' | 'expander' | 'checkbox' | 'icon' | undefined
				 */
				getEventTarget: function (event) {
					var $target,
						tree,
						tcn = event && event.target ? event.target.className : "",
						res = { node: this.getNode(event.target), type: undefined };
					// We use a fast version of $(res.node).hasClass()
					// See http://jsperf.com/test-for-classname/2
					if (/\bfancytree-title\b/.test(tcn)) {
						res.type = "title";
					} else if (/\bfancytree-expander\b/.test(tcn)) {
						res.type =
							res.node.hasChildren() === false
								? "prefix"
								: "expander";
						// }else if( /\bfancytree-checkbox\b/.test(tcn) || /\bfancytree-radio\b/.test(tcn) ){
					} else if (/\bfancytree-checkbox\b/.test(tcn)) {
						res.type = "checkbox";
					} else if (/\bfancytree(-custom)?-icon\b/.test(tcn)) {
						res.type = "icon";
					} else if (/\bfancytree-node\b/.test(tcn)) {
						// Somewhere near the title
						res.type = "title";
					} else if (event && event.target) {
						$target = $(event.target);
						if ($target.is("ul[role=group]")) {
							// #nnn: Clicking right to a node may hit the surrounding UL
							tree = res.node && res.node.tree;
							(tree || FT).debug("Ignoring click on outer UL.");
							res.node = null;
						} else if ($target.closest(".fancytree-title").length) {
							// #228: clicking an embedded element inside a title
							res.type = "title";
						} else if ($target.closest(".fancytree-checkbox").length) {
							// E.g. <svg> inside checkbox span
							res.type = "checkbox";
						} else if ($target.closest(".fancytree-expander").length) {
							res.type = "expander";
						}
					}
					return res;
				},
				/** Return a string describing the affected node region for a mouse event.
				 *
				 * @param {Event} event Mouse event, e.g. click, mousemove, ...
				 * @returns {string} 'title' | 'prefix' | 'expander' | 'checkbox' | 'icon' | undefined
				 */
				getEventTargetType: function (event) {
					return this.getEventTarget(event).type;
				},
				/** Return a FancytreeNode instance from element, event, or jQuery object.
				 *
				 * @param {Element | jQueryObject | Event} el
				 * @returns {FancytreeNode} matching node or null
				 */
				getNode: function (el) {
					if (el instanceof FancytreeNode) {
						return el; // el already was a FancytreeNode
					} else if (el instanceof $) {
						el = el[0]; // el was a jQuery object: use the DOM element
					} else if (el.originalEvent !== undefined) {
						el = el.target; // el was an Event
					}
					while (el) {
						if (el.ftnode) {
							return el.ftnode;
						}
						el = el.parentNode;
					}
					return null;
				},
				/** Return a Fancytree instance, from element, index, event, or jQueryObject.
				 *
				 * @param {Element | jQueryObject | Event | integer | string} [el]
				 * @returns {Fancytree} matching tree or null
				 * @example
				 * $.ui.fancytree.getTree();  // Get first Fancytree instance on page
				 * $.ui.fancytree.getTree(1);  // Get second Fancytree instance on page
				 * $.ui.fancytree.getTree(event);  // Get tree for this mouse- or keyboard event
				 * $.ui.fancytree.getTree("foo");  // Get tree for this `opts.treeId`
				 * $.ui.fancytree.getTree("#tree");  // Get tree for this matching element
				 *
				 * @since 2.13
				 */
				getTree: function (el) {
					var widget,
						orgEl = el;

					if (el instanceof Fancytree) {
						return el; // el already was a Fancytree
					}
					if (el === undefined) {
						el = 0; // get first tree
					}
					if (typeof el === "number") {
						el = $(".fancytree-container").eq(el); // el was an integer: return nth instance
					} else if (typeof el === "string") {
						// `el` may be a treeId or a selector:
						el = $("#ft-id-" + orgEl).eq(0);
						if (!el.length) {
							el = $(orgEl).eq(0); // el was a selector: use first match
						}
					} else if (
						el instanceof Element ||
						el instanceof HTMLDocument
					) {
						el = $(el);
					} else if (el instanceof $) {
						el = el.eq(0); // el was a jQuery object: use the first
					} else if (el.originalEvent !== undefined) {
						el = $(el.target); // el was an Event
					}
					// el is a jQuery object wit one element here
					el = el.closest(":ui-fancytree");
					widget = el.data("ui-fancytree") || el.data("fancytree"); // the latter is required by jQuery <= 1.8
					return widget ? widget.tree : null;
				},
				/** Return an option value that has a default, but may be overridden by a
				 * callback or a node instance attribute.
				 *
				 * Evaluation sequence:
				 *
				 * If `tree.options.<optionName>` is a callback that returns something, use that.
				 * Else if `node.<optionName>` is defined, use that.
				 * Else if `tree.options.<optionName>` is a value, use that.
				 * Else use `defaultValue`.
				 *
				 * @param {string} optionName name of the option property (on node and tree)
				 * @param {FancytreeNode} node passed to the callback
				 * @param {object} nodeObject where to look for the local option property, e.g. `node` or `node.data`
				 * @param {object} treeOption where to look for the tree option, e.g. `tree.options` or `tree.options.dnd5`
				 * @param {any} [defaultValue]
				 * @returns {any}
				 *
				 * @example
				 * // Check for node.foo, tree,options.foo(), and tree.options.foo:
				 * $.ui.fancytree.evalOption("foo", node, node, tree.options);
				 * // Check for node.data.bar, tree,options.qux.bar(), and tree.options.qux.bar:
				 * $.ui.fancytree.evalOption("bar", node, node.data, tree.options.qux);
				 *
				 * @since 2.22
				 */
				evalOption: function (
					optionName,
					node,
					nodeObject,
					treeOptions,
					defaultValue
				) {
					var ctx,
						res,
						tree = node.tree,
						treeOpt = treeOptions[optionName],
						nodeOpt = nodeObject[optionName];

					if (_isFunction(treeOpt)) {
						ctx = {
							node: node,
							tree: tree,
							widget: tree.widget,
							options: tree.widget.options,
							typeInfo: tree.types[node.type] || {},
						};
						res = treeOpt.call(tree, { type: optionName }, ctx);
						if (res == null) {
							res = nodeOpt;
						}
					} else {
						res = nodeOpt == null ? treeOpt : nodeOpt;
					}
					if (res == null) {
						res = defaultValue; // no option set at all: return default
					}
					return res;
				},
				/** Set expander, checkbox, or node icon, supporting string and object format.
				 *
				 * @param {Element | jQueryObject} span
				 * @param {string} baseClass
				 * @param {string | object} icon
				 * @since 2.27
				 */
				setSpanIcon: function (span, baseClass, icon) {
					var $span = $(span);

					if (typeof icon === "string") {
						$span.attr("class", baseClass + " " + icon);
					} else {
						// support object syntax: { text: ligature, addClasse: classname }
						if (icon.text) {
							$span.text("" + icon.text);
						} else if (icon.html) {
							span.innerHTML = icon.html;
						}
						$span.attr(
							"class",
							baseClass + " " + (icon.addClass || "")
						);
					}
				},
				/** Convert a keydown or mouse event to a canonical string like 'ctrl+a',
				 * 'ctrl+shift+f2', 'shift+leftdblclick'.
				 *
				 * This is especially handy for switch-statements in event handlers.
				 *
				 * @param {event}
				 * @returns {string}
				 *
				 * @example

				switch( $.ui.fancytree.eventToString(event) ) {
					case "-":
						tree.nodeSetExpanded(ctx, false);
						break;
					case "shift+return":
						tree.nodeSetActive(ctx, true);
						break;
					case "down":
						res = node.navigate(event.which, activate);
						break;
					default:
						handled = false;
				}
				if( handled ){
					event.preventDefault();
				}
				*/
				eventToString: function (event) {
					// Poor-man's hotkeys. See here for a complete implementation:
					//   https://github.com/jeresig/jquery.hotkeys
					var which = event.which,
						et = event.type,
						s = [];

					if (event.altKey) {
						s.push("alt");
					}
					if (event.ctrlKey) {
						s.push("ctrl");
					}
					if (event.metaKey) {
						s.push("meta");
					}
					if (event.shiftKey) {
						s.push("shift");
					}

					if (et === "click" || et === "dblclick") {
						s.push(MOUSE_BUTTONS[event.button] + et);
					} else if (et === "wheel") {
						s.push(et);
					} else if (!IGNORE_KEYCODES[which]) {
						s.push(
							SPECIAL_KEYCODES[which] ||
								String.fromCharCode(which).toLowerCase()
						);
					}
					return s.join("+");
				},
				/** Write message to console if debugLevel >= 3
				 * @param {string} msg
				 */
				info: function (msg) {
					if ($.ui.fancytree.debugLevel >= 3) {
						consoleApply("info", arguments);
					}
				},
				/* @deprecated: use eventToString(event) instead.
				 */
				keyEventToString: function (event) {
					this.warn(
						"keyEventToString() is deprecated: use eventToString()"
					);
					return this.eventToString(event);
				},
				/** Return a wrapped handler method, that provides `this._super`.
				 *
				 * @example
					// Implement `opts.createNode` event to add the 'draggable' attribute
					$.ui.fancytree.overrideMethod(ctx.options, "createNode", function(event, data) {
						// Default processing if any
						this._super.apply(this, arguments);
						// Add 'draggable' attribute
						data.node.span.draggable = true;
					});
				 *
				 * @param {object} instance
				 * @param {string} methodName
				 * @param {function} handler
				 * @param {object} [context] optional context
				 */
				overrideMethod: function (instance, methodName, handler, context) {
					var prevSuper,
						_super = instance[methodName] || $.noop;

					instance[methodName] = function () {
						var self = context || this;

						try {
							prevSuper = self._super;
							self._super = _super;
							return handler.apply(self, arguments);
						} finally {
							self._super = prevSuper;
						}
					};
				},
				/**
				 * Parse tree data from HTML <ul> markup
				 *
				 * @param {jQueryObject} $ul
				 * @returns {NodeData[]}
				 */
				parseHtml: function ($ul) {
					var classes,
						className,
						extraClasses,
						i,
						iPos,
						l,
						tmp,
						tmp2,
						$children = $ul.find(">li"),
						children = [];

					$children.each(function () {
						var allData,
							lowerCaseAttr,
							$li = $(this),
							$liSpan = $li.find(">span", this).first(),
							$liA = $liSpan.length ? null : $li.find(">a").first(),
							d = { tooltip: null, data: {} };

						if ($liSpan.length) {
							d.title = $liSpan.html();
						} else if ($liA && $liA.length) {
							// If a <li><a> tag is specified, use it literally and extract href/target.
							d.title = $liA.html();
							d.data.href = $liA.attr("href");
							d.data.target = $liA.attr("target");
							d.tooltip = $liA.attr("title");
						} else {
							// If only a <li> tag is specified, use the trimmed string up to
							// the next child <ul> tag.
							d.title = $li.html();
							iPos = d.title.search(/<ul/i);
							if (iPos >= 0) {
								d.title = d.title.substring(0, iPos);
							}
						}
						d.title = _trim(d.title);

						// Make sure all fields exist
						for (i = 0, l = CLASS_ATTRS.length; i < l; i++) {
							d[CLASS_ATTRS[i]] = undefined;
						}
						// Initialize to `true`, if class is set and collect extraClasses
						classes = this.className.split(" ");
						extraClasses = [];
						for (i = 0, l = classes.length; i < l; i++) {
							className = classes[i];
							if (CLASS_ATTR_MAP[className]) {
								d[className] = true;
							} else {
								extraClasses.push(className);
							}
						}
						d.extraClasses = extraClasses.join(" ");

						// Parse node options from ID, title and class attributes
						tmp = $li.attr("title");
						if (tmp) {
							d.tooltip = tmp; // overrides <a title='...'>
						}
						tmp = $li.attr("id");
						if (tmp) {
							d.key = tmp;
						}
						// Translate hideCheckbox -> checkbox:false
						if ($li.attr("hideCheckbox")) {
							d.checkbox = false;
						}
						// Add <li data-NAME='...'> as node.data.NAME
						allData = _getElementDataAsDict($li);
						if (allData && !$.isEmptyObject(allData)) {
							// #507: convert data-hidecheckbox (lower case) to hideCheckbox
							for (lowerCaseAttr in NODE_ATTR_LOWERCASE_MAP) {
								if (_hasProp(allData, lowerCaseAttr)) {
									allData[
										NODE_ATTR_LOWERCASE_MAP[lowerCaseAttr]
									] = allData[lowerCaseAttr];
									delete allData[lowerCaseAttr];
								}
							}
							// #56: Allow to set special node.attributes from data-...
							for (i = 0, l = NODE_ATTRS.length; i < l; i++) {
								tmp = NODE_ATTRS[i];
								tmp2 = allData[tmp];
								if (tmp2 != null) {
									delete allData[tmp];
									d[tmp] = tmp2;
								}
							}
							// All other data-... goes to node.data...
							$.extend(d.data, allData);
						}
						// Recursive reading of child nodes, if LI tag contains an UL tag
						$ul = $li.find(">ul").first();
						if ($ul.length) {
							d.children = $.ui.fancytree.parseHtml($ul);
						} else {
							d.children = d.lazy ? undefined : null;
						}
						children.push(d);
						// FT.debug("parse ", d, children);
					});
					return children;
				},
				/** Add Fancytree extension definition to the list of globally available extensions.
				 *
				 * @param {object} definition
				 */
				registerExtension: function (definition) {
					_assert(
						definition.name != null,
						"extensions must have a `name` property."
					);
					_assert(
						definition.version != null,
						"extensions must have a `version` property."
					);
					$.ui.fancytree._extensions[definition.name] = definition;
				},
				/** Replacement for the deprecated `jQuery.trim()`.
				 *
				 * @param {string} text
				 */
				trim: _trim,
				/** Inverse of escapeHtml().
				 *
				 * @param {string} s
				 * @returns {string}
				 */
				unescapeHtml: function (s) {
					var e = document.createElement("div");
					e.innerHTML = s;
					return e.childNodes.length === 0
						? ""
						: e.childNodes[0].nodeValue;
				},
				/** Write warning message to console if debugLevel >= 2.
				 * @param {string} msg
				 */
				warn: function (msg) {
					if ($.ui.fancytree.debugLevel >= 2) {
						consoleApply("warn", arguments);
					}
				},
			}
		);

		// Value returned by `require('jquery.fancytree')`
		return $.ui.fancytree;
	}); // End of closure


/***/ }),
/* 8 */
/***/ (function(module, exports, __webpack_require__) {

	var __WEBPACK_AMD_DEFINE_FACTORY__, __WEBPACK_AMD_DEFINE_ARRAY__, __WEBPACK_AMD_DEFINE_RESULT__;/*! jQuery UI - v1.13.2 - 2022-08-16
	* http://jqueryui.com
	* Includes: widget.js, position.js, jquery-patch.js, keycode.js, scroll-parent.js, unique-id.js
	* Copyright jQuery Foundation and other contributors; Licensed MIT */

	( function( factory ) {
		"use strict";
		
		if ( true ) {

			// AMD. Register as an anonymous module.
			!(__WEBPACK_AMD_DEFINE_ARRAY__ = [ __webpack_require__(3) ], __WEBPACK_AMD_DEFINE_FACTORY__ = (factory), __WEBPACK_AMD_DEFINE_RESULT__ = (typeof __WEBPACK_AMD_DEFINE_FACTORY__ === 'function' ? (__WEBPACK_AMD_DEFINE_FACTORY__.apply(exports, __WEBPACK_AMD_DEFINE_ARRAY__)) : __WEBPACK_AMD_DEFINE_FACTORY__), __WEBPACK_AMD_DEFINE_RESULT__ !== undefined && (module.exports = __WEBPACK_AMD_DEFINE_RESULT__));
		} else {

			// Browser globals
			factory( jQuery );
		}
	} )( function( $ ) {
	"use strict";

	$.ui = $.ui || {};

	var version = $.ui.version = "1.13.2";


	/*!
	 * jQuery UI Widget 1.13.2
	 * http://jqueryui.com
	 *
	 * Copyright jQuery Foundation and other contributors
	 * Released under the MIT license.
	 * http://jquery.org/license
	 */

	//>>label: Widget
	//>>group: Core
	//>>description: Provides a factory for creating stateful widgets with a common API.
	//>>docs: http://api.jqueryui.com/jQuery.widget/
	//>>demos: http://jqueryui.com/widget/


	var widgetUuid = 0;
	var widgetHasOwnProperty = Array.prototype.hasOwnProperty;
	var widgetSlice = Array.prototype.slice;

	$.cleanData = $.cleanData || ( function( orig ) {
		return function( elems ) {
			var events, elem, i;
			for ( i = 0; ( elem = elems[ i ] ) != null; i++ ) {

				// Only trigger remove when necessary to save time
				events = $._data( elem, "events" );
				if ( events && events.remove ) {
					$( elem ).triggerHandler( "remove" );
				}
			}
			orig( elems );
		};
	} )( $.cleanData );

	$.widget = $.widget || function( name, base, prototype ) {
		var existingConstructor, constructor, basePrototype;

		// ProxiedPrototype allows the provided prototype to remain unmodified
		// so that it can be used as a mixin for multiple widgets (#8876)
		var proxiedPrototype = {};

		var namespace = name.split( "." )[ 0 ];
		name = name.split( "." )[ 1 ];
		var fullName = namespace + "-" + name;

		if ( !prototype ) {
			prototype = base;
			base = $.Widget;
		}

		if ( Array.isArray( prototype ) ) {
			prototype = $.extend.apply( null, [ {} ].concat( prototype ) );
		}

		// Create selector for plugin
		$.expr.pseudos[ fullName.toLowerCase() ] = function( elem ) {
			return !!$.data( elem, fullName );
		};

		$[ namespace ] = $[ namespace ] || {};
		existingConstructor = $[ namespace ][ name ];
		constructor = $[ namespace ][ name ] = function( options, element ) {

			// Allow instantiation without "new" keyword
			if ( !this || !this._createWidget ) {
				return new constructor( options, element );
			}

			// Allow instantiation without initializing for simple inheritance
			// must use "new" keyword (the code above always passes args)
			if ( arguments.length ) {
				this._createWidget( options, element );
			}
		};

		// Extend with the existing constructor to carry over any static properties
		$.extend( constructor, existingConstructor, {
			version: prototype.version,

			// Copy the object used to create the prototype in case we need to
			// redefine the widget later
			_proto: $.extend( {}, prototype ),

			// Track widgets that inherit from this widget in case this widget is
			// redefined after a widget inherits from it
			_childConstructors: []
		} );

		basePrototype = new base();

		// We need to make the options hash a property directly on the new instance
		// otherwise we'll modify the options hash on the prototype that we're
		// inheriting from
		basePrototype.options = $.widget.extend( {}, basePrototype.options );
		$.each( prototype, function( prop, value ) {
			if ( typeof value !== "function" ) {
				proxiedPrototype[ prop ] = value;
				return;
			}
			proxiedPrototype[ prop ] = ( function() {
				function _super() {
					return base.prototype[ prop ].apply( this, arguments );
				}

				function _superApply( args ) {
					return base.prototype[ prop ].apply( this, args );
				}

				return function() {
					var __super = this._super;
					var __superApply = this._superApply;
					var returnValue;

					this._super = _super;
					this._superApply = _superApply;

					returnValue = value.apply( this, arguments );

					this._super = __super;
					this._superApply = __superApply;

					return returnValue;
				};
			} )();
		} );
		constructor.prototype = $.widget.extend( basePrototype, {

			// TODO: remove support for widgetEventPrefix
			// always use the name + a colon as the prefix, e.g., draggable:start
			// don't prefix for widgets that aren't DOM-based
			widgetEventPrefix: existingConstructor ? ( basePrototype.widgetEventPrefix || name ) : name
		}, proxiedPrototype, {
			constructor: constructor,
			namespace: namespace,
			widgetName: name,
			widgetFullName: fullName
		} );

		// If this widget is being redefined then we need to find all widgets that
		// are inheriting from it and redefine all of them so that they inherit from
		// the new version of this widget. We're essentially trying to replace one
		// level in the prototype chain.
		if ( existingConstructor ) {
			$.each( existingConstructor._childConstructors, function( i, child ) {
				var childPrototype = child.prototype;

				// Redefine the child widget using the same prototype that was
				// originally used, but inherit from the new version of the base
				$.widget( childPrototype.namespace + "." + childPrototype.widgetName, constructor,
					child._proto );
			} );

			// Remove the list of existing child constructors from the old constructor
			// so the old child constructors can be garbage collected
			delete existingConstructor._childConstructors;
		} else {
			base._childConstructors.push( constructor );
		}

		$.widget.bridge( name, constructor );

		return constructor;
	};

	$.widget.extend = function( target ) {
		var input = widgetSlice.call( arguments, 1 );
		var inputIndex = 0;
		var inputLength = input.length;
		var key;
		var value;

		for ( ; inputIndex < inputLength; inputIndex++ ) {
			for ( key in input[ inputIndex ] ) {
				value = input[ inputIndex ][ key ];
				if ( widgetHasOwnProperty.call( input[ inputIndex ], key ) && value !== undefined ) {

					// Clone objects
					if ( $.isPlainObject( value ) ) {
						target[ key ] = $.isPlainObject( target[ key ] ) ?
							$.widget.extend( {}, target[ key ], value ) :

							// Don't extend strings, arrays, etc. with objects
							$.widget.extend( {}, value );

					// Copy everything else by reference
					} else {
						target[ key ] = value;
					}
				}
			}
		}
		return target;
	};

	$.widget.bridge = function( name, object ) {
		var fullName = object.prototype.widgetFullName || name;
		$.fn[ name ] = function( options ) {
			var isMethodCall = typeof options === "string";
			var args = widgetSlice.call( arguments, 1 );
			var returnValue = this;

			if ( isMethodCall ) {

				// If this is an empty collection, we need to have the instance method
				// return undefined instead of the jQuery instance
				if ( !this.length && options === "instance" ) {
					returnValue = undefined;
				} else {
					this.each( function() {
						var methodValue;
						var instance = $.data( this, fullName );

						if ( options === "instance" ) {
							returnValue = instance;
							return false;
						}

						if ( !instance ) {
							return $.error( "cannot call methods on " + name +
								" prior to initialization; " +
								"attempted to call method '" + options + "'" );
						}

						if ( typeof instance[ options ] !== "function" ||
							options.charAt( 0 ) === "_" ) {
							return $.error( "no such method '" + options + "' for " + name +
								" widget instance" );
						}

						methodValue = instance[ options ].apply( instance, args );

						if ( methodValue !== instance && methodValue !== undefined ) {
							returnValue = methodValue && methodValue.jquery ?
								returnValue.pushStack( methodValue.get() ) :
								methodValue;
							return false;
						}
					} );
				}
			} else {

				// Allow multiple hashes to be passed on init
				if ( args.length ) {
					options = $.widget.extend.apply( null, [ options ].concat( args ) );
				}

				this.each( function() {
					var instance = $.data( this, fullName );
					if ( instance ) {
						instance.option( options || {} );
						if ( instance._init ) {
							instance._init();
						}
					} else {
						$.data( this, fullName, new object( options, this ) );
					}
				} );
			}

			return returnValue;
		};
	};

	$.Widget = $.Widget || function( /* options, element */ ) {};
	$.Widget._childConstructors = [];

	$.Widget.prototype = {
		widgetName: "widget",
		widgetEventPrefix: "",
		defaultElement: "<div>",

		options: {
			classes: {},
			disabled: false,

			// Callbacks
			create: null
		},

		_createWidget: function( options, element ) {
			element = $( element || this.defaultElement || this )[ 0 ];
			this.element = $( element );
			this.uuid = widgetUuid++;
			this.eventNamespace = "." + this.widgetName + this.uuid;

			this.bindings = $();
			this.hoverable = $();
			this.focusable = $();
			this.classesElementLookup = {};

			if ( element !== this ) {
				$.data( element, this.widgetFullName, this );
				this._on( true, this.element, {
					remove: function( event ) {
						if ( event.target === element ) {
							this.destroy();
						}
					}
				} );
				this.document = $( element.style ?

					// Element within the document
					element.ownerDocument :

					// Element is window or document
					element.document || element );
				this.window = $( this.document[ 0 ].defaultView || this.document[ 0 ].parentWindow );
			}

			this.options = $.widget.extend( {},
				this.options,
				this._getCreateOptions(),
				options );

			this._create();

			if ( this.options.disabled ) {
				this._setOptionDisabled( this.options.disabled );
			}

			this._trigger( "create", null, this._getCreateEventData() );
			this._init();
		},

		_getCreateOptions: function() {
			return {};
		},

		_getCreateEventData: $.noop,

		_create: $.noop,

		_init: $.noop,

		destroy: function() {
			var that = this;

			this._destroy();
			$.each( this.classesElementLookup, function( key, value ) {
				that._removeClass( value, key );
			} );

			// We can probably remove the unbind calls in 2.0
			// all event bindings should go through this._on()
			this.element
				.off( this.eventNamespace )
				.removeData( this.widgetFullName );
			this.widget()
				.off( this.eventNamespace )
				.removeAttr( "aria-disabled" );

			// Clean up events and states
			this.bindings.off( this.eventNamespace );
		},

		_destroy: $.noop,

		widget: function() {
			return this.element;
		},

		option: function( key, value ) {
			var options = key;
			var parts;
			var curOption;
			var i;

			if ( arguments.length === 0 ) {

				// Don't return a reference to the internal hash
				return $.widget.extend( {}, this.options );
			}

			if ( typeof key === "string" ) {

				// Handle nested keys, e.g., "foo.bar" => { foo: { bar: ___ } }
				options = {};
				parts = key.split( "." );
				key = parts.shift();
				if ( parts.length ) {
					curOption = options[ key ] = $.widget.extend( {}, this.options[ key ] );
					for ( i = 0; i < parts.length - 1; i++ ) {
						curOption[ parts[ i ] ] = curOption[ parts[ i ] ] || {};
						curOption = curOption[ parts[ i ] ];
					}
					key = parts.pop();
					if ( arguments.length === 1 ) {
						return curOption[ key ] === undefined ? null : curOption[ key ];
					}
					curOption[ key ] = value;
				} else {
					if ( arguments.length === 1 ) {
						return this.options[ key ] === undefined ? null : this.options[ key ];
					}
					options[ key ] = value;
				}
			}

			this._setOptions( options );

			return this;
		},

		_setOptions: function( options ) {
			var key;

			for ( key in options ) {
				this._setOption( key, options[ key ] );
			}

			return this;
		},

		_setOption: function( key, value ) {
			if ( key === "classes" ) {
				this._setOptionClasses( value );
			}

			this.options[ key ] = value;

			if ( key === "disabled" ) {
				this._setOptionDisabled( value );
			}

			return this;
		},

		_setOptionClasses: function( value ) {
			var classKey, elements, currentElements;

			for ( classKey in value ) {
				currentElements = this.classesElementLookup[ classKey ];
				if ( value[ classKey ] === this.options.classes[ classKey ] ||
						!currentElements ||
						!currentElements.length ) {
					continue;
				}

				// We are doing this to create a new jQuery object because the _removeClass() call
				// on the next line is going to destroy the reference to the current elements being
				// tracked. We need to save a copy of this collection so that we can add the new classes
				// below.
				elements = $( currentElements.get() );
				this._removeClass( currentElements, classKey );

				// We don't use _addClass() here, because that uses this.options.classes
				// for generating the string of classes. We want to use the value passed in from
				// _setOption(), this is the new value of the classes option which was passed to
				// _setOption(). We pass this value directly to _classes().
				elements.addClass( this._classes( {
					element: elements,
					keys: classKey,
					classes: value,
					add: true
				} ) );
			}
		},

		_setOptionDisabled: function( value ) {
			this._toggleClass( this.widget(), this.widgetFullName + "-disabled", null, !!value );

			// If the widget is becoming disabled, then nothing is interactive
			if ( value ) {
				this._removeClass( this.hoverable, null, "ui-state-hover" );
				this._removeClass( this.focusable, null, "ui-state-focus" );
			}
		},

		enable: function() {
			return this._setOptions( { disabled: false } );
		},

		disable: function() {
			return this._setOptions( { disabled: true } );
		},

		_classes: function( options ) {
			var full = [];
			var that = this;

			options = $.extend( {
				element: this.element,
				classes: this.options.classes || {}
			}, options );

			function bindRemoveEvent() {
				var nodesToBind = [];

				options.element.each( function( _, element ) {
					var isTracked = $.map( that.classesElementLookup, function( elements ) {
						return elements;
					} )
						.some( function( elements ) {
							return elements.is( element );
						} );

					if ( !isTracked ) {
						nodesToBind.push( element );
					}
				} );

				that._on( $( nodesToBind ), {
					remove: "_untrackClassesElement"
				} );
			}

			function processClassString( classes, checkOption ) {
				var current, i;
				for ( i = 0; i < classes.length; i++ ) {
					current = that.classesElementLookup[ classes[ i ] ] || $();
					if ( options.add ) {
						bindRemoveEvent();
						current = $( $.uniqueSort( current.get().concat( options.element.get() ) ) );
					} else {
						current = $( current.not( options.element ).get() );
					}
					that.classesElementLookup[ classes[ i ] ] = current;
					full.push( classes[ i ] );
					if ( checkOption && options.classes[ classes[ i ] ] ) {
						full.push( options.classes[ classes[ i ] ] );
					}
				}
			}

			if ( options.keys ) {
				processClassString( options.keys.match( /\S+/g ) || [], true );
			}
			if ( options.extra ) {
				processClassString( options.extra.match( /\S+/g ) || [] );
			}

			return full.join( " " );
		},

		_untrackClassesElement: function( event ) {
			var that = this;
			$.each( that.classesElementLookup, function( key, value ) {
				if ( $.inArray( event.target, value ) !== -1 ) {
					that.classesElementLookup[ key ] = $( value.not( event.target ).get() );
				}
			} );

			this._off( $( event.target ) );
		},

		_removeClass: function( element, keys, extra ) {
			return this._toggleClass( element, keys, extra, false );
		},

		_addClass: function( element, keys, extra ) {
			return this._toggleClass( element, keys, extra, true );
		},

		_toggleClass: function( element, keys, extra, add ) {
			add = ( typeof add === "boolean" ) ? add : extra;
			var shift = ( typeof element === "string" || element === null ),
				options = {
					extra: shift ? keys : extra,
					keys: shift ? element : keys,
					element: shift ? this.element : element,
					add: add
				};
			options.element.toggleClass( this._classes( options ), add );
			return this;
		},

		_on: function( suppressDisabledCheck, element, handlers ) {
			var delegateElement;
			var instance = this;

			// No suppressDisabledCheck flag, shuffle arguments
			if ( typeof suppressDisabledCheck !== "boolean" ) {
				handlers = element;
				element = suppressDisabledCheck;
				suppressDisabledCheck = false;
			}

			// No element argument, shuffle and use this.element
			if ( !handlers ) {
				handlers = element;
				element = this.element;
				delegateElement = this.widget();
			} else {
				element = delegateElement = $( element );
				this.bindings = this.bindings.add( element );
			}

			$.each( handlers, function( event, handler ) {
				function handlerProxy() {

					// Allow widgets to customize the disabled handling
					// - disabled as an array instead of boolean
					// - disabled class as method for disabling individual parts
					if ( !suppressDisabledCheck &&
							( instance.options.disabled === true ||
							$( this ).hasClass( "ui-state-disabled" ) ) ) {
						return;
					}
					return ( typeof handler === "string" ? instance[ handler ] : handler )
						.apply( instance, arguments );
				}

				// Copy the guid so direct unbinding works
				if ( typeof handler !== "string" ) {
					handlerProxy.guid = handler.guid =
						handler.guid || handlerProxy.guid || $.guid++;
				}

				var match = event.match( /^([\w:-]*)\s*(.*)$/ );
				var eventName = match[ 1 ] + instance.eventNamespace;
				var selector = match[ 2 ];

				if ( selector ) {
					delegateElement.on( eventName, selector, handlerProxy );
				} else {
					element.on( eventName, handlerProxy );
				}
			} );
		},

		_off: function( element, eventName ) {
			eventName = ( eventName || "" ).split( " " ).join( this.eventNamespace + " " ) +
				this.eventNamespace;
			element.off( eventName );

			// Clear the stack to avoid memory leaks (#10056)
			this.bindings = $( this.bindings.not( element ).get() );
			this.focusable = $( this.focusable.not( element ).get() );
			this.hoverable = $( this.hoverable.not( element ).get() );
		},

		_delay: function( handler, delay ) {
			function handlerProxy() {
				return ( typeof handler === "string" ? instance[ handler ] : handler )
					.apply( instance, arguments );
			}
			var instance = this;
			return setTimeout( handlerProxy, delay || 0 );
		},

		_hoverable: function( element ) {
			this.hoverable = this.hoverable.add( element );
			this._on( element, {
				mouseenter: function( event ) {
					this._addClass( $( event.currentTarget ), null, "ui-state-hover" );
				},
				mouseleave: function( event ) {
					this._removeClass( $( event.currentTarget ), null, "ui-state-hover" );
				}
			} );
		},

		_focusable: function( element ) {
			this.focusable = this.focusable.add( element );
			this._on( element, {
				focusin: function( event ) {
					this._addClass( $( event.currentTarget ), null, "ui-state-focus" );
				},
				focusout: function( event ) {
					this._removeClass( $( event.currentTarget ), null, "ui-state-focus" );
				}
			} );
		},

		_trigger: function( type, event, data ) {
			var prop, orig;
			var callback = this.options[ type ];

			data = data || {};
			event = $.Event( event );
			event.type = ( type === this.widgetEventPrefix ?
				type :
				this.widgetEventPrefix + type ).toLowerCase();

			// The original event may come from any element
			// so we need to reset the target on the new event
			event.target = this.element[ 0 ];

			// Copy original event properties over to the new event
			orig = event.originalEvent;
			if ( orig ) {
				for ( prop in orig ) {
					if ( !( prop in event ) ) {
						event[ prop ] = orig[ prop ];
					}
				}
			}

			this.element.trigger( event, data );
			return !( typeof callback === "function" &&
				callback.apply( this.element[ 0 ], [ event ].concat( data ) ) === false ||
				event.isDefaultPrevented() );
		}
	};

	$.each( { show: "fadeIn", hide: "fadeOut" }, function( method, defaultEffect ) {
		$.Widget.prototype[ "_" + method ] = function( element, options, callback ) {
			if ( typeof options === "string" ) {
				options = { effect: options };
			}

			var hasOptions;
			var effectName = !options ?
				method :
				options === true || typeof options === "number" ?
					defaultEffect :
					options.effect || defaultEffect;

			options = options || {};
			if ( typeof options === "number" ) {
				options = { duration: options };
			} else if ( options === true ) {
				options = {};
			}

			hasOptions = !$.isEmptyObject( options );
			options.complete = callback;

			if ( options.delay ) {
				element.delay( options.delay );
			}

			if ( hasOptions && $.effects && $.effects.effect[ effectName ] ) {
				element[ method ]( options );
			} else if ( effectName !== method && element[ effectName ] ) {
				element[ effectName ]( options.duration, options.easing, callback );
			} else {
				element.queue( function( next ) {
					$( this )[ method ]();
					if ( callback ) {
						callback.call( element[ 0 ] );
					}
					next();
				} );
			}
		};
	} );

	var widget = $.widget;


	/*!
	 * jQuery UI Position 1.13.2
	 * http://jqueryui.com
	 *
	 * Copyright jQuery Foundation and other contributors
	 * Released under the MIT license.
	 * http://jquery.org/license
	 *
	 * http://api.jqueryui.com/position/
	 */

	//>>label: Position
	//>>group: Core
	//>>description: Positions elements relative to other elements.
	//>>docs: http://api.jqueryui.com/position/
	//>>demos: http://jqueryui.com/position/


	( function() {
	var cachedScrollbarWidth,
		max = Math.max,
		abs = Math.abs,
		rhorizontal = /left|center|right/,
		rvertical = /top|center|bottom/,
		roffset = /[\+\-]\d+(\.[\d]+)?%?/,
		rposition = /^\w+/,
		rpercent = /%$/,
		_position = $.fn.position;

	function getOffsets( offsets, width, height ) {
		return [
			parseFloat( offsets[ 0 ] ) * ( rpercent.test( offsets[ 0 ] ) ? width / 100 : 1 ),
			parseFloat( offsets[ 1 ] ) * ( rpercent.test( offsets[ 1 ] ) ? height / 100 : 1 )
		];
	}

	function parseCss( element, property ) {
		return parseInt( $.css( element, property ), 10 ) || 0;
	}

	function isWindow( obj ) {
		return obj != null && obj === obj.window;
	}

	function getDimensions( elem ) {
		var raw = elem[ 0 ];
		if ( raw.nodeType === 9 ) {
			return {
				width: elem.width(),
				height: elem.height(),
				offset: { top: 0, left: 0 }
			};
		}
		if ( isWindow( raw ) ) {
			return {
				width: elem.width(),
				height: elem.height(),
				offset: { top: elem.scrollTop(), left: elem.scrollLeft() }
			};
		}
		if ( raw.preventDefault ) {
			return {
				width: 0,
				height: 0,
				offset: { top: raw.pageY, left: raw.pageX }
			};
		}
		return {
			width: elem.outerWidth(),
			height: elem.outerHeight(),
			offset: elem.offset()
		};
	}

	$.position = $.position || {
		scrollbarWidth: function() {
			if ( cachedScrollbarWidth !== undefined ) {
				return cachedScrollbarWidth;
			}
			var w1, w2,
				div = $( "<div style=" +
					"'display:block;position:absolute;width:200px;height:200px;overflow:hidden;'>" +
					"<div style='height:300px;width:auto;'></div></div>" ),
				innerDiv = div.children()[ 0 ];

			$( "body" ).append( div );
			w1 = innerDiv.offsetWidth;
			div.css( "overflow", "scroll" );

			w2 = innerDiv.offsetWidth;

			if ( w1 === w2 ) {
				w2 = div[ 0 ].clientWidth;
			}

			div.remove();

			return ( cachedScrollbarWidth = w1 - w2 );
		},
		getScrollInfo: function( within ) {
			var overflowX = within.isWindow || within.isDocument ? "" :
					within.element.css( "overflow-x" ),
				overflowY = within.isWindow || within.isDocument ? "" :
					within.element.css( "overflow-y" ),
				hasOverflowX = overflowX === "scroll" ||
					( overflowX === "auto" && within.width < within.element[ 0 ].scrollWidth ),
				hasOverflowY = overflowY === "scroll" ||
					( overflowY === "auto" && within.height < within.element[ 0 ].scrollHeight );
			return {
				width: hasOverflowY ? $.position.scrollbarWidth() : 0,
				height: hasOverflowX ? $.position.scrollbarWidth() : 0
			};
		},
		getWithinInfo: function( element ) {
			var withinElement = $( element || window ),
				isElemWindow = isWindow( withinElement[ 0 ] ),
				isDocument = !!withinElement[ 0 ] && withinElement[ 0 ].nodeType === 9,
				hasOffset = !isElemWindow && !isDocument;
			return {
				element: withinElement,
				isWindow: isElemWindow,
				isDocument: isDocument,
				offset: hasOffset ? $( element ).offset() : { left: 0, top: 0 },
				scrollLeft: withinElement.scrollLeft(),
				scrollTop: withinElement.scrollTop(),
				width: withinElement.outerWidth(),
				height: withinElement.outerHeight()
			};
		}
	};

	$.fn.position = function( options ) {
		if ( !options || !options.of ) {
			return _position.apply( this, arguments );
		}

		// Make a copy, we don't want to modify arguments
		options = $.extend( {}, options );

		var atOffset, targetWidth, targetHeight, targetOffset, basePosition, dimensions,

			// Make sure string options are treated as CSS selectors
			target = typeof options.of === "string" ?
				$( document ).find( options.of ) :
				$( options.of ),

			within = $.position.getWithinInfo( options.within ),
			scrollInfo = $.position.getScrollInfo( within ),
			collision = ( options.collision || "flip" ).split( " " ),
			offsets = {};

		dimensions = getDimensions( target );
		if ( target[ 0 ].preventDefault ) {

			// Force left top to allow flipping
			options.at = "left top";
		}
		targetWidth = dimensions.width;
		targetHeight = dimensions.height;
		targetOffset = dimensions.offset;

		// Clone to reuse original targetOffset later
		basePosition = $.extend( {}, targetOffset );

		// Force my and at to have valid horizontal and vertical positions
		// if a value is missing or invalid, it will be converted to center
		$.each( [ "my", "at" ], function() {
			var pos = ( options[ this ] || "" ).split( " " ),
				horizontalOffset,
				verticalOffset;

			if ( pos.length === 1 ) {
				pos = rhorizontal.test( pos[ 0 ] ) ?
					pos.concat( [ "center" ] ) :
					rvertical.test( pos[ 0 ] ) ?
						[ "center" ].concat( pos ) :
						[ "center", "center" ];
			}
			pos[ 0 ] = rhorizontal.test( pos[ 0 ] ) ? pos[ 0 ] : "center";
			pos[ 1 ] = rvertical.test( pos[ 1 ] ) ? pos[ 1 ] : "center";

			// Calculate offsets
			horizontalOffset = roffset.exec( pos[ 0 ] );
			verticalOffset = roffset.exec( pos[ 1 ] );
			offsets[ this ] = [
				horizontalOffset ? horizontalOffset[ 0 ] : 0,
				verticalOffset ? verticalOffset[ 0 ] : 0
			];

			// Reduce to just the positions without the offsets
			options[ this ] = [
				rposition.exec( pos[ 0 ] )[ 0 ],
				rposition.exec( pos[ 1 ] )[ 0 ]
			];
		} );

		// Normalize collision option
		if ( collision.length === 1 ) {
			collision[ 1 ] = collision[ 0 ];
		}

		if ( options.at[ 0 ] === "right" ) {
			basePosition.left += targetWidth;
		} else if ( options.at[ 0 ] === "center" ) {
			basePosition.left += targetWidth / 2;
		}

		if ( options.at[ 1 ] === "bottom" ) {
			basePosition.top += targetHeight;
		} else if ( options.at[ 1 ] === "center" ) {
			basePosition.top += targetHeight / 2;
		}

		atOffset = getOffsets( offsets.at, targetWidth, targetHeight );
		basePosition.left += atOffset[ 0 ];
		basePosition.top += atOffset[ 1 ];

		return this.each( function() {
			var collisionPosition, using,
				elem = $( this ),
				elemWidth = elem.outerWidth(),
				elemHeight = elem.outerHeight(),
				marginLeft = parseCss( this, "marginLeft" ),
				marginTop = parseCss( this, "marginTop" ),
				collisionWidth = elemWidth + marginLeft + parseCss( this, "marginRight" ) +
					scrollInfo.width,
				collisionHeight = elemHeight + marginTop + parseCss( this, "marginBottom" ) +
					scrollInfo.height,
				position = $.extend( {}, basePosition ),
				myOffset = getOffsets( offsets.my, elem.outerWidth(), elem.outerHeight() );

			if ( options.my[ 0 ] === "right" ) {
				position.left -= elemWidth;
			} else if ( options.my[ 0 ] === "center" ) {
				position.left -= elemWidth / 2;
			}

			if ( options.my[ 1 ] === "bottom" ) {
				position.top -= elemHeight;
			} else if ( options.my[ 1 ] === "center" ) {
				position.top -= elemHeight / 2;
			}

			position.left += myOffset[ 0 ];
			position.top += myOffset[ 1 ];

			collisionPosition = {
				marginLeft: marginLeft,
				marginTop: marginTop
			};

			$.each( [ "left", "top" ], function( i, dir ) {
				if ( $.ui.position[ collision[ i ] ] ) {
					$.ui.position[ collision[ i ] ][ dir ]( position, {
						targetWidth: targetWidth,
						targetHeight: targetHeight,
						elemWidth: elemWidth,
						elemHeight: elemHeight,
						collisionPosition: collisionPosition,
						collisionWidth: collisionWidth,
						collisionHeight: collisionHeight,
						offset: [ atOffset[ 0 ] + myOffset[ 0 ], atOffset [ 1 ] + myOffset[ 1 ] ],
						my: options.my,
						at: options.at,
						within: within,
						elem: elem
					} );
				}
			} );

			if ( options.using ) {

				// Adds feedback as second argument to using callback, if present
				using = function( props ) {
					var left = targetOffset.left - position.left,
						right = left + targetWidth - elemWidth,
						top = targetOffset.top - position.top,
						bottom = top + targetHeight - elemHeight,
						feedback = {
							target: {
								element: target,
								left: targetOffset.left,
								top: targetOffset.top,
								width: targetWidth,
								height: targetHeight
							},
							element: {
								element: elem,
								left: position.left,
								top: position.top,
								width: elemWidth,
								height: elemHeight
							},
							horizontal: right < 0 ? "left" : left > 0 ? "right" : "center",
							vertical: bottom < 0 ? "top" : top > 0 ? "bottom" : "middle"
						};
					if ( targetWidth < elemWidth && abs( left + right ) < targetWidth ) {
						feedback.horizontal = "center";
					}
					if ( targetHeight < elemHeight && abs( top + bottom ) < targetHeight ) {
						feedback.vertical = "middle";
					}
					if ( max( abs( left ), abs( right ) ) > max( abs( top ), abs( bottom ) ) ) {
						feedback.important = "horizontal";
					} else {
						feedback.important = "vertical";
					}
					options.using.call( this, props, feedback );
				};
			}

			elem.offset( $.extend( position, { using: using } ) );
		} );
	};

	$.ui.position = {
		fit: {
			left: function( position, data ) {
				var within = data.within,
					withinOffset = within.isWindow ? within.scrollLeft : within.offset.left,
					outerWidth = within.width,
					collisionPosLeft = position.left - data.collisionPosition.marginLeft,
					overLeft = withinOffset - collisionPosLeft,
					overRight = collisionPosLeft + data.collisionWidth - outerWidth - withinOffset,
					newOverRight;

				// Element is wider than within
				if ( data.collisionWidth > outerWidth ) {

					// Element is initially over the left side of within
					if ( overLeft > 0 && overRight <= 0 ) {
						newOverRight = position.left + overLeft + data.collisionWidth - outerWidth -
							withinOffset;
						position.left += overLeft - newOverRight;

					// Element is initially over right side of within
					} else if ( overRight > 0 && overLeft <= 0 ) {
						position.left = withinOffset;

					// Element is initially over both left and right sides of within
					} else {
						if ( overLeft > overRight ) {
							position.left = withinOffset + outerWidth - data.collisionWidth;
						} else {
							position.left = withinOffset;
						}
					}

				// Too far left -> align with left edge
				} else if ( overLeft > 0 ) {
					position.left += overLeft;

				// Too far right -> align with right edge
				} else if ( overRight > 0 ) {
					position.left -= overRight;

				// Adjust based on position and margin
				} else {
					position.left = max( position.left - collisionPosLeft, position.left );
				}
			},
			top: function( position, data ) {
				var within = data.within,
					withinOffset = within.isWindow ? within.scrollTop : within.offset.top,
					outerHeight = data.within.height,
					collisionPosTop = position.top - data.collisionPosition.marginTop,
					overTop = withinOffset - collisionPosTop,
					overBottom = collisionPosTop + data.collisionHeight - outerHeight - withinOffset,
					newOverBottom;

				// Element is taller than within
				if ( data.collisionHeight > outerHeight ) {

					// Element is initially over the top of within
					if ( overTop > 0 && overBottom <= 0 ) {
						newOverBottom = position.top + overTop + data.collisionHeight - outerHeight -
							withinOffset;
						position.top += overTop - newOverBottom;

					// Element is initially over bottom of within
					} else if ( overBottom > 0 && overTop <= 0 ) {
						position.top = withinOffset;

					// Element is initially over both top and bottom of within
					} else {
						if ( overTop > overBottom ) {
							position.top = withinOffset + outerHeight - data.collisionHeight;
						} else {
							position.top = withinOffset;
						}
					}

				// Too far up -> align with top
				} else if ( overTop > 0 ) {
					position.top += overTop;

				// Too far down -> align with bottom edge
				} else if ( overBottom > 0 ) {
					position.top -= overBottom;

				// Adjust based on position and margin
				} else {
					position.top = max( position.top - collisionPosTop, position.top );
				}
			}
		},
		flip: {
			left: function( position, data ) {
				var within = data.within,
					withinOffset = within.offset.left + within.scrollLeft,
					outerWidth = within.width,
					offsetLeft = within.isWindow ? within.scrollLeft : within.offset.left,
					collisionPosLeft = position.left - data.collisionPosition.marginLeft,
					overLeft = collisionPosLeft - offsetLeft,
					overRight = collisionPosLeft + data.collisionWidth - outerWidth - offsetLeft,
					myOffset = data.my[ 0 ] === "left" ?
						-data.elemWidth :
						data.my[ 0 ] === "right" ?
							data.elemWidth :
							0,
					atOffset = data.at[ 0 ] === "left" ?
						data.targetWidth :
						data.at[ 0 ] === "right" ?
							-data.targetWidth :
							0,
					offset = -2 * data.offset[ 0 ],
					newOverRight,
					newOverLeft;

				if ( overLeft < 0 ) {
					newOverRight = position.left + myOffset + atOffset + offset + data.collisionWidth -
						outerWidth - withinOffset;
					if ( newOverRight < 0 || newOverRight < abs( overLeft ) ) {
						position.left += myOffset + atOffset + offset;
					}
				} else if ( overRight > 0 ) {
					newOverLeft = position.left - data.collisionPosition.marginLeft + myOffset +
						atOffset + offset - offsetLeft;
					if ( newOverLeft > 0 || abs( newOverLeft ) < overRight ) {
						position.left += myOffset + atOffset + offset;
					}
				}
			},
			top: function( position, data ) {
				var within = data.within,
					withinOffset = within.offset.top + within.scrollTop,
					outerHeight = within.height,
					offsetTop = within.isWindow ? within.scrollTop : within.offset.top,
					collisionPosTop = position.top - data.collisionPosition.marginTop,
					overTop = collisionPosTop - offsetTop,
					overBottom = collisionPosTop + data.collisionHeight - outerHeight - offsetTop,
					top = data.my[ 1 ] === "top",
					myOffset = top ?
						-data.elemHeight :
						data.my[ 1 ] === "bottom" ?
							data.elemHeight :
							0,
					atOffset = data.at[ 1 ] === "top" ?
						data.targetHeight :
						data.at[ 1 ] === "bottom" ?
							-data.targetHeight :
							0,
					offset = -2 * data.offset[ 1 ],
					newOverTop,
					newOverBottom;
				if ( overTop < 0 ) {
					newOverBottom = position.top + myOffset + atOffset + offset + data.collisionHeight -
						outerHeight - withinOffset;
					if ( newOverBottom < 0 || newOverBottom < abs( overTop ) ) {
						position.top += myOffset + atOffset + offset;
					}
				} else if ( overBottom > 0 ) {
					newOverTop = position.top - data.collisionPosition.marginTop + myOffset + atOffset +
						offset - offsetTop;
					if ( newOverTop > 0 || abs( newOverTop ) < overBottom ) {
						position.top += myOffset + atOffset + offset;
					}
				}
			}
		},
		flipfit: {
			left: function() {
				$.ui.position.flip.left.apply( this, arguments );
				$.ui.position.fit.left.apply( this, arguments );
			},
			top: function() {
				$.ui.position.flip.top.apply( this, arguments );
				$.ui.position.fit.top.apply( this, arguments );
			}
		}
	};

	} )();

	var position = $.ui.position;


	/*!
	 * jQuery UI Support for jQuery core 1.8.x and newer 1.13.2
	 * http://jqueryui.com
	 *
	 * Copyright jQuery Foundation and other contributors
	 * Released under the MIT license.
	 * http://jquery.org/license
	 *
	 */

	//>>label: jQuery 1.8+ Support
	//>>group: Core
	//>>description: Support version 1.8.x and newer of jQuery core


	// Support: jQuery 1.9.x or older
	// $.expr[ ":" ] is deprecated.
	if ( !$.expr.pseudos ) {
		$.expr.pseudos = $.expr[ ":" ];
	}

	// Support: jQuery 1.11.x or older
	// $.unique has been renamed to $.uniqueSort
	if ( !$.uniqueSort ) {
		$.uniqueSort = $.unique;
	}

	// Support: jQuery 2.2.x or older.
	// This method has been defined in jQuery 3.0.0.
	// Code from https://github.com/jquery/jquery/blob/e539bac79e666bba95bba86d690b4e609dca2286/src/selector/escapeSelector.js
	if ( !$.escapeSelector ) {

		// CSS string/identifier serialization
		// https://drafts.csswg.org/cssom/#common-serializing-idioms
		var rcssescape = /([\0-\x1f\x7f]|^-?\d)|^-$|[^\x80-\uFFFF\w-]/g;

		var fcssescape = function( ch, asCodePoint ) {
			if ( asCodePoint ) {

				// U+0000 NULL becomes U+FFFD REPLACEMENT CHARACTER
				if ( ch === "\0" ) {
					return "\uFFFD";
				}

				// Control characters and (dependent upon position) numbers get escaped as code points
				return ch.slice( 0, -1 ) + "\\" + ch.charCodeAt( ch.length - 1 ).toString( 16 ) + " ";
			}

			// Other potentially-special ASCII characters get backslash-escaped
			return "\\" + ch;
		};

		$.escapeSelector = function( sel ) {
			return ( sel + "" ).replace( rcssescape, fcssescape );
		};
	}

	// Support: jQuery 3.4.x or older
	// These methods have been defined in jQuery 3.5.0.
	if ( !$.fn.even || !$.fn.odd ) {
		$.fn.extend( {
			even: function() {
				return this.filter( function( i ) {
					return i % 2 === 0;
				} );
			},
			odd: function() {
				return this.filter( function( i ) {
					return i % 2 === 1;
				} );
			}
		} );
	}

	;
	/*!
	 * jQuery UI Keycode 1.13.2
	 * http://jqueryui.com
	 *
	 * Copyright jQuery Foundation and other contributors
	 * Released under the MIT license.
	 * http://jquery.org/license
	 */

	//>>label: Keycode
	//>>group: Core
	//>>description: Provide keycodes as keynames
	//>>docs: http://api.jqueryui.com/jQuery.ui.keyCode/


	var keycode = $.ui.keyCode = {
		BACKSPACE: 8,
		COMMA: 188,
		DELETE: 46,
		DOWN: 40,
		END: 35,
		ENTER: 13,
		ESCAPE: 27,
		HOME: 36,
		LEFT: 37,
		PAGE_DOWN: 34,
		PAGE_UP: 33,
		PERIOD: 190,
		RIGHT: 39,
		SPACE: 32,
		TAB: 9,
		UP: 38
	};


	/*!
	 * jQuery UI Scroll Parent 1.13.2
	 * http://jqueryui.com
	 *
	 * Copyright jQuery Foundation and other contributors
	 * Released under the MIT license.
	 * http://jquery.org/license
	 */

	//>>label: scrollParent
	//>>group: Core
	//>>description: Get the closest ancestor element that is scrollable.
	//>>docs: http://api.jqueryui.com/scrollParent/


	var scrollParent = $.fn.scrollParent = function( includeHidden ) {
		var position = this.css( "position" ),
			excludeStaticParent = position === "absolute",
			overflowRegex = includeHidden ? /(auto|scroll|hidden)/ : /(auto|scroll)/,
			scrollParent = this.parents().filter( function() {
				var parent = $( this );
				if ( excludeStaticParent && parent.css( "position" ) === "static" ) {
					return false;
				}
				return overflowRegex.test( parent.css( "overflow" ) + parent.css( "overflow-y" ) +
					parent.css( "overflow-x" ) );
			} ).eq( 0 );

		return position === "fixed" || !scrollParent.length ?
			$( this[ 0 ].ownerDocument || document ) :
			scrollParent;
	};


	/*!
	 * jQuery UI Unique ID 1.13.2
	 * http://jqueryui.com
	 *
	 * Copyright jQuery Foundation and other contributors
	 * Released under the MIT license.
	 * http://jquery.org/license
	 */

	//>>label: uniqueId
	//>>group: Core
	//>>description: Functions to generate and remove uniqueId's
	//>>docs: http://api.jqueryui.com/uniqueId/


	var uniqueId = $.fn.extend( {
		uniqueId: ( function() {
			var uuid = 0;

			return function() {
				return this.each( function() {
					if ( !this.id ) {
						this.id = "ui-id-" + ( ++uuid );
					}
				} );
			};
		} )(),

		removeUniqueId: function() {
			return this.each( function() {
				if ( /^ui-id-\d+$/.test( this.id ) ) {
					$( this ).removeAttr( "id" );
				}
			} );
		}
	} );




	} );

/***/ }),
/* 9 */
/***/ (function(module, exports, __webpack_require__) {

	var __WEBPACK_AMD_DEFINE_FACTORY__, __WEBPACK_AMD_DEFINE_ARRAY__, __WEBPACK_AMD_DEFINE_RESULT__;/*!
	 * jquery.fancytree.glyph.js
	 *
	 * Use glyph-fonts, ligature-fonts, or SVG icons instead of icon sprites.
	 * (Extension module for jquery.fancytree.js: https://github.com/mar10/fancytree/)
	 *
	 * Copyright (c) 2008-2023, Martin Wendt (https://wwWendt.de)
	 *
	 * Released under the MIT license
	 * https://github.com/mar10/fancytree/wiki/LicenseInfo
	 *
	 * @version 2.38.3
	 * @date 2023-02-01T20:52:50Z
	 */

	(function (factory) {
		if (true) {
			// AMD. Register as an anonymous module.
			!(__WEBPACK_AMD_DEFINE_ARRAY__ = [__webpack_require__(3), __webpack_require__(7)], __WEBPACK_AMD_DEFINE_FACTORY__ = (factory), __WEBPACK_AMD_DEFINE_RESULT__ = (typeof __WEBPACK_AMD_DEFINE_FACTORY__ === 'function' ? (__WEBPACK_AMD_DEFINE_FACTORY__.apply(exports, __WEBPACK_AMD_DEFINE_ARRAY__)) : __WEBPACK_AMD_DEFINE_FACTORY__), __WEBPACK_AMD_DEFINE_RESULT__ !== undefined && (module.exports = __WEBPACK_AMD_DEFINE_RESULT__));
		} else if (typeof module === "object" && module.exports) {
			// Node/CommonJS
			require("./jquery.fancytree");
			module.exports = factory(require("jquery"));
		} else {
			// Browser globals
			factory(jQuery);
		}
	})(function ($) {
		"use strict";

		/******************************************************************************
		 * Private functions and variables
		 */

		var FT = $.ui.fancytree,
			PRESETS = {
				awesome3: {
					// Outdated!
					_addClass: "",
					checkbox: "icon-check-empty",
					checkboxSelected: "icon-check",
					checkboxUnknown: "icon-check icon-muted",
					dragHelper: "icon-caret-right",
					dropMarker: "icon-caret-right",
					error: "icon-exclamation-sign",
					expanderClosed: "icon-caret-right",
					expanderLazy: "icon-angle-right",
					expanderOpen: "icon-caret-down",
					loading: "icon-refresh icon-spin",
					nodata: "icon-meh",
					noExpander: "",
					radio: "icon-circle-blank",
					radioSelected: "icon-circle",
					// radioUnknown: "icon-circle icon-muted",
					// Default node icons.
					// (Use tree.options.icon callback to define custom icons based on node data)
					doc: "icon-file-alt",
					docOpen: "icon-file-alt",
					folder: "icon-folder-close-alt",
					folderOpen: "icon-folder-open-alt",
				},
				awesome4: {
					_addClass: "fa",
					checkbox: "fa-square-o",
					checkboxSelected: "fa-check-square-o",
					checkboxUnknown: "fa-square fancytree-helper-indeterminate-cb",
					dragHelper: "fa-arrow-right",
					dropMarker: "fa-long-arrow-right",
					error: "fa-warning",
					expanderClosed: "fa-caret-right",
					expanderLazy: "fa-angle-right",
					expanderOpen: "fa-caret-down",
					// We may prevent wobbling rotations on FF by creating a separate sub element:
					loading: { html: "<span class='fa fa-spinner fa-pulse' />" },
					nodata: "fa-meh-o",
					noExpander: "",
					radio: "fa-circle-thin", // "fa-circle-o"
					radioSelected: "fa-circle",
					// radioUnknown: "fa-dot-circle-o",
					// Default node icons.
					// (Use tree.options.icon callback to define custom icons based on node data)
					doc: "fa-file-o",
					docOpen: "fa-file-o",
					folder: "fa-folder-o",
					folderOpen: "fa-folder-open-o",
				},
				awesome5: {
					// fontawesome 5 have several different base classes
					// "far, fas, fal and fab" The rendered svg puts that prefix
					// in a different location so we have to keep them separate here
					_addClass: "",
					checkbox: "far fa-square",
					checkboxSelected: "far fa-check-square",
					// checkboxUnknown: "far fa-window-close",
					checkboxUnknown:
						"fas fa-square fancytree-helper-indeterminate-cb",
					radio: "far fa-circle",
					radioSelected: "fas fa-circle",
					radioUnknown: "far fa-dot-circle",
					dragHelper: "fas fa-arrow-right",
					dropMarker: "fas fa-long-arrow-alt-right",
					error: "fas fa-exclamation-triangle",
					expanderClosed: "fas fa-caret-right",
					expanderLazy: "fas fa-angle-right",
					expanderOpen: "fas fa-caret-down",
					loading: "fas fa-spinner fa-pulse",
					nodata: "far fa-meh",
					noExpander: "",
					// Default node icons.
					// (Use tree.options.icon callback to define custom icons based on node data)
					doc: "far fa-file",
					docOpen: "far fa-file",
					folder: "far fa-folder",
					folderOpen: "far fa-folder-open",
				},
				bootstrap3: {
					_addClass: "glyphicon",
					checkbox: "glyphicon-unchecked",
					checkboxSelected: "glyphicon-check",
					checkboxUnknown:
						"glyphicon-expand fancytree-helper-indeterminate-cb", // "glyphicon-share",
					dragHelper: "glyphicon-play",
					dropMarker: "glyphicon-arrow-right",
					error: "glyphicon-warning-sign",
					expanderClosed: "glyphicon-menu-right", // glyphicon-plus-sign
					expanderLazy: "glyphicon-menu-right", // glyphicon-plus-sign
					expanderOpen: "glyphicon-menu-down", // glyphicon-minus-sign
					loading: "glyphicon-refresh fancytree-helper-spin",
					nodata: "glyphicon-info-sign",
					noExpander: "",
					radio: "glyphicon-remove-circle", // "glyphicon-unchecked",
					radioSelected: "glyphicon-ok-circle", // "glyphicon-check",
					// radioUnknown: "glyphicon-ban-circle",
					// Default node icons.
					// (Use tree.options.icon callback to define custom icons based on node data)
					doc: "glyphicon-file",
					docOpen: "glyphicon-file",
					folder: "glyphicon-folder-close",
					folderOpen: "glyphicon-folder-open",
				},
				material: {
					_addClass: "material-icons",
					checkbox: { text: "check_box_outline_blank" },
					checkboxSelected: { text: "check_box" },
					checkboxUnknown: { text: "indeterminate_check_box" },
					dragHelper: { text: "play_arrow" },
					dropMarker: { text: "arrow-forward" },
					error: { text: "warning" },
					expanderClosed: { text: "chevron_right" },
					expanderLazy: { text: "last_page" },
					expanderOpen: { text: "expand_more" },
					loading: {
						text: "autorenew",
						addClass: "fancytree-helper-spin",
					},
					nodata: { text: "info" },
					noExpander: { text: "" },
					radio: { text: "radio_button_unchecked" },
					radioSelected: { text: "radio_button_checked" },
					// Default node icons.
					// (Use tree.options.icon callback to define custom icons based on node data)
					doc: { text: "insert_drive_file" },
					docOpen: { text: "insert_drive_file" },
					folder: { text: "folder" },
					folderOpen: { text: "folder_open" },
				},
			};

		function setIcon(node, span, baseClass, opts, type) {
			var map = opts.map,
				icon = map[type],
				$span = $(span),
				$counter = $span.find(".fancytree-childcounter"),
				setClass = baseClass + " " + (map._addClass || "");

			// #871 Allow a callback
			if (typeof icon === "function") {
				icon = icon.call(this, node, span, type);
			}
			// node.debug( "setIcon(" + baseClass + ", " + type + "): " + "oldIcon" + " -> " + icon );
			// #871: propsed this, but I am not sure how robust this is, e.g.
			// the prefix (fas, far) class changes are not considered?
			// if (span.tagName === "svg" && opts.preset === "awesome5") {
			// 	// fa5 script converts <i> to <svg> so call a specific handler.
			// 	var oldIcon = "fa-" + $span.data("icon");
			// 	// node.debug( "setIcon(" + baseClass + ", " + type + "): " + oldIcon + " -> " + icon );
			// 	if (typeof oldIcon === "string") {
			// 		$span.removeClass(oldIcon);
			// 	}
			// 	if (typeof icon === "string") {
			// 		$span.addClass(icon);
			// 	}
			// 	return;
			// }
			if (typeof icon === "string") {
				// #883: remove inner html that may be added by prev. mode
				span.innerHTML = "";
				$span.attr("class", setClass + " " + icon).append($counter);
			} else if (icon) {
				if (icon.text) {
					span.textContent = "" + icon.text;
				} else if (icon.html) {
					span.innerHTML = icon.html;
				} else {
					span.innerHTML = "";
				}
				$span
					.attr("class", setClass + " " + (icon.addClass || ""))
					.append($counter);
			}
		}

		$.ui.fancytree.registerExtension({
			name: "glyph",
			version: "2.38.3",
			// Default options for this extension.
			options: {
				preset: null, // 'awesome3', 'awesome4', 'bootstrap3', 'material'
				map: {},
			},

			treeInit: function (ctx) {
				var tree = ctx.tree,
					opts = ctx.options.glyph;

				if (opts.preset) {
					FT.assert(
						!!PRESETS[opts.preset],
						"Invalid value for `options.glyph.preset`: " + opts.preset
					);
					opts.map = $.extend({}, PRESETS[opts.preset], opts.map);
				} else {
					tree.warn("ext-glyph: missing `preset` option.");
				}
				this._superApply(arguments);
				tree.$container.addClass("fancytree-ext-glyph");
			},
			nodeRenderStatus: function (ctx) {
				var checkbox,
					icon,
					res,
					span,
					node = ctx.node,
					$span = $(node.span),
					opts = ctx.options.glyph;

				res = this._super(ctx);

				if (node.isRootNode()) {
					return res;
				}
				span = $span.children(".fancytree-expander").get(0);
				if (span) {
					// if( node.isLoading() ){
					// icon = "loading";
					if (node.expanded && node.hasChildren()) {
						icon = "expanderOpen";
					} else if (node.isUndefined()) {
						icon = "expanderLazy";
					} else if (node.hasChildren()) {
						icon = "expanderClosed";
					} else {
						icon = "noExpander";
					}
					// span.className = "fancytree-expander " + map[icon];
					setIcon(node, span, "fancytree-expander", opts, icon);
				}

				if (node.tr) {
					span = $("td", node.tr).find(".fancytree-checkbox").get(0);
				} else {
					span = $span.children(".fancytree-checkbox").get(0);
				}
				if (span) {
					checkbox = FT.evalOption("checkbox", node, node, opts, false);
					if (
						(node.parent && node.parent.radiogroup) ||
						checkbox === "radio"
					) {
						icon = node.selected ? "radioSelected" : "radio";
						setIcon(
							node,
							span,
							"fancytree-checkbox fancytree-radio",
							opts,
							icon
						);
					} else {
						// eslint-disable-next-line no-nested-ternary
						icon = node.selected
							? "checkboxSelected"
							: node.partsel
							? "checkboxUnknown"
							: "checkbox";
						// span.className = "fancytree-checkbox " + map[icon];
						setIcon(node, span, "fancytree-checkbox", opts, icon);
					}
				}

				// Standard icon (note that this does not match .fancytree-custom-icon,
				// that might be set by opts.icon callbacks)
				span = $span.children(".fancytree-icon").get(0);
				if (span) {
					if (node.statusNodeType) {
						icon = node.statusNodeType; // loading, error
					} else if (node.folder) {
						icon =
							node.expanded && node.hasChildren()
								? "folderOpen"
								: "folder";
					} else {
						icon = node.expanded ? "docOpen" : "doc";
					}
					setIcon(node, span, "fancytree-icon", opts, icon);
				}
				return res;
			},
			nodeSetStatus: function (ctx, status, message, details) {
				var res,
					span,
					opts = ctx.options.glyph,
					node = ctx.node;

				res = this._superApply(arguments);

				if (
					status === "error" ||
					status === "loading" ||
					status === "nodata"
				) {
					if (node.parent) {
						span = $(".fancytree-expander", node.span).get(0);
						if (span) {
							setIcon(node, span, "fancytree-expander", opts, status);
						}
					} else {
						//
						span = $(
							".fancytree-statusnode-" + status,
							node[this.nodeContainerAttrName]
						)
							.find(".fancytree-icon")
							.get(0);
						if (span) {
							setIcon(node, span, "fancytree-icon", opts, status);
						}
					}
				}
				return res;
			},
		});
		// Value returned by `require('jquery.fancytree..')`
		return $.ui.fancytree;
	}); // End of closure


/***/ })
/******/ ])});;