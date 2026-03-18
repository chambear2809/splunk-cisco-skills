define([
	    "app-js/contrib/underscore",
		"app-js/contrib/jquery",
		"app-js/contrib/backbone",
		'app-components/stepwizard/BaseStepView',
		'swc-stream/index',
		'contrib/text!app-components/stepwizard/StepWizardView.html',
		'css!app-components/stepwizard/StepWizardView.css',
		'@splunk/ui-utils/i18n'
	],
	function(
		_,
		$,
		Backbone,
		BaseStepView,
		index,
		template,
		CSS,
		Inter
	) {
		const FlashMessagesLegacyView = index.FlashMessagesLegacyView;
		const FlashMessagesCollection = index.FlashMessagesCollection;
		var compiledTemplate = _.template(template, null, {variable: "vars"});
		/**
		 * Provides a navigation menu/wizard interface in as generic a fashion
		 * as possible.
		 * @constructor
		 * @module
		 */
		var StepWizardView = Backbone.View.extend({
			//
			// Overloads of Backbone Methods/Properties
			//
			/**
			 * @param options {Object} initialization options
			 * @param options.label {string} a text label to show to the left of the control itself, optional
			 * @param options.stepContainer {element|$|selector} the place into which to append the content of a step
			 * @param options.operatingMode {String} whether to act as a navigation system or a wizard, pass options of 'nav' or 'wizard' (defaults to 'wizard')
			 * @param options.navBackgroundColor {String} i am sorry for this one, but this is the color to assign to the inactive circle interiors in nav mode default is white (see CSS for the sadness that precipitated this decision)
			 * @param options.showExitButton {Boolean} whether to render an Exit button, optional, defaults to false
			 * @param options.steps {Array}: an array of BaseStepView to represent the steps in the flow, each step should define the following as internal properties
			 *		 - value {String} the value to set on the control model when the active step changes
			 *		 - label {String} the label to display to the user
			 *		 - visible {Boolean} whether the step is currently visible, optional, defaults to true
			 *		 - enabled {Boolean} whether the step is currently enabled, optional, defaults to true
			 *		 - nextLabel {String} the label to the show in the next button (not including the '>' icon),
			 *							  optional, defaults to 'Next'
			 *		 - previousLabel {String} the label to the show in the previous button (not including the '<' icon),
			 *							  optional, defaults to ''
			 *		 - showNextButton {Boolean} whether to show the next button, optional, defaults to true
			 *		 - showPreviousButton {Boolean} whether to show the previous button, optional, defaults to true
			 */
			initialize: function(options) {
				options = options || {};
				this._disabled = false;
				this.$el.addClass('step-wizard');

				this.label = options.label || '';
				/**
				 * the place we append step content
				 * @type {$}
				 * @private
				 */
				this.$stepContainer = $(options.stepContainer);
				if (this.$stepContainer.length !== 1) {
					throw("StepWizardView must be supplied with a stepContainer option that is a single valid place to stick steps!");
				}
				if (options.steps instanceof Array) {
					/**
					 * Steps is the structure that determines the different UI
					 * elements to show
					 * @type {Array/BaseStepView}
					 * @private
					 */
					this.steps = options.steps;

					/**
					 * Allow for the steps to issue events for the wizard
					 */
					this.dispatcher = _.extend({}, Backbone.Events);
					for (var i = 0; i < this.steps.length; ++i) {
						this.steps[i].setEventDispatcher(this.dispatcher);
					}
					this.dispatcher.on('stepforward', this.stepForward, this);
					this.dispatcher.on('customerror', function(step, errorMsg) {
						this.flashMessagesCollection.reset({
							key: 'validationError',
							type: 'error',
							html: errorMsg
						});
					}, this);
					this.dispatcher.on('clearerror', function(step) {
						this.flashMessagesCollection.reset();
					}, this);

				}
				else {
					throw("StepWizardView requires an instantiation option of steps as an array of BaseStepView");
				}
				if (_.contains(['nav', 'wizard'], options.operatingMode)) {
					/**
					 * determines if we are a wizard or a nav
					 * @type {String}
					 * @public
					 */
					this.operatingMode = options.operatingMode;
				}
				else {
					this.operatingMode = 'wizard';
				}
				/**
				 * the background color to give circles in nav mode to get around fixing the awful css.
				 * @type {String}
				 * @private
				 */
				this.navBackgroundColor = options.navBackgroundColor || "#FFFFFF";
				/**
				 * Determines if we should show the exit button or not.
				 * @type {Boolean}
				 * @private
				 */
				this.showExitButton = options.showExitButton || false;

				/**
				 * Track the active step view
				 * @type {BaseStepView}
				 * @private
				 */
				this.activeStep = _.find(this.steps, function(step) { return step.visible; });
				if (this.activeStep === undefined) {
					throw("StepWizardView requires there be at least 1 visible step in the steps option");
				}

				/** To support showing error messages on wizard navigation header */
				this.flashMessagesCollection = new FlashMessagesCollection();
				this.flashMessagesLegacy = new FlashMessagesLegacyView({
					collection: this.flashMessagesCollection
				});

			},

			/**
			 * The base events to be bound to the View by Backbone
			 * @type {Object}
			 * @protected
			 */
			baseEvents: {
				'click .previous-button': function(e) {
					e.preventDefault();
					if(!$(e.currentTarget).is('.disabled')) {
						this.stepBack();
					}
				},
				'click .next-button': function(e) {
					e.preventDefault();
					if(!$(e.currentTarget).is('.disabled')) {
						this.stepForward();
					}
				},
				'click .save-button': function(e) {
					e.preventDefault();
					if(!$(e.currentTarget).is('.disabled')) {
						this.saveAndExit();
					}
				},
				'click .exit-button': function(e) {
					e.preventDefault();
					if(!$(e.target).is('.disabled')) {
						this.trigger('exit');
					}
				}
			},

			navClickEvent: {
				'click .step-container': function(e) {
					e.preventDefault();
					var value, stepView;
					var $target = $(e.currentTarget);
					if(!$target.is('.disabled')) {
						value = $target.data("value");
						stepView = _.find(this.steps, function(step) { return step.value === value; });
						this.step(stepView);
					}
				}
			},

			/**
			 * use a function to allow events to be bound differently based on operatingMode
			 * @returns {Object} Backbone event routing object
			 */
			events: function() {
				if (this.operatingMode === "nav") {
					this.$el.addClass('step-wizard-nav');
					return _.extend({}, this.baseEvents, this.navClickEvent);
				}
				return this.baseEvents;
			},

			enable: function() {
				this._disabled = false;
				this.updateNavButtons();
				this.$('.exit-button').removeClass('disabled');
			},

			disable: function() {
				this._disabled = true;
				this.$('.next-button, .previous-button, .exit-button').addClass('disabled');
			},

			/**
			 * step the wizard to the previous visible step assuming validation
			 * passes.
			 * @returns {$.Deferred} the active step validation promise
			 */
			stepBack: function() {
				var selectedValue = this.activeStep.value,
					selectedIndex = this.steps.indexOf(this.activeStep),
					prevVisible = this.steps[selectedIndex - 1].visible;

				// Find the prev visible step
				while (prevVisible === false && selectedIndex > 1) {
					selectedIndex -= 1;
					prevVisible = this.steps[selectedIndex + 1].visible;
				}

				return this.step(selectedIndex - 1, true);
			},

			/**
			 * step the wizard to the next visible step assuming validation
			 * passes.
			 * @returns {$.Deferred} the active step validation promise
			 */
			stepForward: function() {
				var selectedValue = this.activeStep.value,
					selectedIndex = this.steps.indexOf(this.activeStep),
					nextVisible = this.steps[selectedIndex + 1].visible;

				// Find the next visible step
				while (nextVisible === false && selectedIndex <= this.steps.length) {
					selectedIndex += 1;
					nextVisible = this.steps[selectedIndex + 1].visible;
				}

				return this.step(selectedIndex + 1);
			},

			/**
			 * step the wizard to the next visible step assuming validation
			 * passes.
			 * @returns {$.Deferred} the active step validation promise
			 */
			saveAndExit: function() {
				$(window).unbind('beforeunload');
				this.disableNavButtons();
				var promise = this.activeStep.validate();
				promise.done(function() {
					var savePromise = this.activeStep.save();
					savePromise.done(function () {
						this.enableNavButtons();
						this.trigger('exit');
					}.bind(this))
					.fail(function (message) {
						this.enableNavButtons();
						if (!message || typeof message !== 'string') {
							message = Inter.gettext('Error saving');
						}
						this.flashMessagesCollection.reset([{
							key: 'saveError',
							type: 'error',
							html: message
						}]);
					}.bind(this));
				}.bind(this))
				.fail(function(message) {
					this.enableNavButtons();
					if (!message || typeof message !== 'string') {
						message = Inter.gettext('Validation failed');
					}
					this.flashMessagesCollection.reset([{
						key: 'validationError',
						type: 'error',
						html: message
					}]);
				}.bind(this));
				return promise;
			},

			/**
			 * set the active step to an arbitrary step. Note this is an async
			 * operation dependent on the current step's validate routine passing.
			 * Returns the validate promise should the user wish to perform
			 * additional binding to it.
			 * @param {BaseStepView|Number} newStep, either the new step view itself or its index in this.steps
			 * @param {Boolean} [stepBack] - If true it means we are stepping back in the wizard
			 * @returns {$.Deferred} the current step's validation promise
			 */
			step: function(newStep, stepBack) {
				if (!(newStep instanceof BaseStepView)) {
					newStep = this.steps[newStep];
					if (!(newStep instanceof BaseStepView)) {
						throw("Invalid step index attempted to be set active, index must represent a BaseStepView");
					}
				}
				this.disableNavButtons();
				var promise = this.activeStep.validate(newStep);
				var that = this;
				promise.done(function() {
					that.flashMessagesCollection.reset();
					that.activeStep.deactivate();
					var savePromise = that.activeStep.save(stepBack);
					savePromise.done(function() {
						that.enableNavButtons();
						that.activeStep = newStep;
						that.updateSelectedStep();
						that.updateNavButtons();
						that.activeStep.activate();
					}).fail(function (message) {
						that.enableNavButtons();
						if (!message || typeof message !== 'string') {
							message = Inter.gettext('Error saving');
						}
						that.flashMessagesCollection.reset([{
							key: 'validationError',
							type: 'error',
							html: message
						}]);
					});
				}).fail(function (message) {
					that.enableNavButtons();
					if (!message || typeof message !== 'string') {
						message = Inter.gettext('Error validating');
					}
					that.flashMessagesCollection.reset([{
						key: 'validationError',
						type: 'error',
						html: message
					}]);
				});
				return promise;
			},

			/**
			 * Update the UI to reflect the currently active step
			 * @param {Boolean} doActivate, if true run the activate routine
			 */
			updateSelectedStep: function(doActivate) {
				var selectedValue = this.activeStep.value,
					$stepContainers = this.$('.step-container'),
					$selectedContainer = $stepContainers.filter('[data-value="' + selectedValue + '"]'),
					selectedIndex = $selectedContainer.index();

				// Handle the Wizard UI
				$stepContainers.removeClass('active');
				if (this.operatingMode === "wizard") {
					$stepContainers.removeClass('completed');
					$stepContainers.slice(0, selectedIndex).addClass('completed');
				}
				else {
					$stepContainers.find(".circle").css({"background-color": this.navBackgroundColor});
					$selectedContainer.find(".circle").css({"background-color": "#4e802a"});
				}
				$selectedContainer.addClass('active').removeClass('completed');

				// Append step into the stepContainer
				this.$stepContainer.children().detach();
				this.$stepContainer.append(this.activeStep.el);
				if (doActivate) {
					this.activeStep.activate();
				}
				this.trigger('stepactivated', this.activeStep);
			},

			/**
			 * Update the navigation buttons for the current step and mode.
			 */
			updateNavButtons: function() {
				var selectedValue = this.activeStep.value,
					selectedIndex = this.steps.indexOf(this.activeStep),
					nextIndex = selectedIndex + 1,
					prevIndex = selectedIndex - 1,
					nextIsValid = (nextIndex < this.steps.length),
					nextIsVisible = this.activeStep.showNextButton !== false && nextIsValid,
					saveIsVisible = !nextIsValid || this.operatingMode === 'nav',
					nextEnabled = nextIsValid && this.steps[nextIndex].enabled !== false,
					prevIsVisible = this.activeStep.showPreviousButton !== false,
					prevIsValid = (prevIndex >= 0),
					prevEnabled = prevIsValid && this.steps[prevIndex].enabled !== false,
					$nextButton = this.$('.next-button'),
					$saveButton = this.$('.save-button'),
					$previousButton = this.$('.previous-button');

				if(nextEnabled && !this._disabled) {
					$nextButton.removeClass('disabled');
				}
				else {
					$nextButton.addClass('disabled');
				}
				if(prevEnabled && !this._disabled) {
					$previousButton.removeClass('disabled');
				}
				else {
					$previousButton.addClass('disabled');
				}
				if (nextIsVisible) {
					$nextButton.show();
				}
				else {
					$nextButton.hide();
				}
				if (prevIsVisible) {
					$previousButton.show();
				}
				else {
					$previousButton.hide();
				}
				if (saveIsVisible) {
					$saveButton.show();
				} else {
					$saveButton.hide();
				}
				$nextButton.find('.button-text').text(this.activeStep.nextLabel || '');
				$saveButton.find('.button-text').text(this.activeStep.saveLabel || Inter.gettext('Save & Exit'));
				$previousButton.find('.button-text').text(this.activeStep.previousLabel || '');
			},

			disableNavButtons: function() {
				$('.nav-buttons .btn').addClass('disabled');
			},

			enableNavButtons: function() {
				$('.nav-buttons .btn').removeClass('disabled');
			},
	
			/**
			 * renders the wizard in its container and the active step in the stepContainer
			 * @returns {StepWizardView} this
			 */
			render: function() {
				var filteredCollection = this.steps.filter(function(step) {
					var visible = step.visible;
					return visible !== false;
				});
				this.$el.html(compiledTemplate({
					_: _,
					inter: Inter,
					label: this.label,
					steps: filteredCollection,
					exitButton: this.showExitButton,
					operatingMode: this.operatingMode
				}, {variable: "vars"}));
				this.$('.flashmessages-header-placeholder').html(this.flashMessagesLegacy.render().el);
				this.updateSelectedStep(true);
				this.updateNavButtons();
				return this;
			},

			/**
			 * Switch the operating mode.  Will re-render and manipulate events
			 * @param operatingMode valid values are 'nav' and 'wizard'
			 */
			updateOperatingMode: function(operatingMode) {
				if (this.operatingMode === operatingMode) {
					return;//noop
				}
				if (operatingMode !== 'nav' && operatingMode !== 'wizard') {
					throw('Unrecognized operatingMode "' + operatingMode + '". Only "nav" or "wizard" is supported');
				}
				this.operatingMode = operatingMode;
				if (this.operatingMode === 'nav') {
					this.$el.addClass('step-wizard-nav');
					this.delegateEvents(_.extend({}, this.baseEvents, this.navClickEvent));
				} else {
					this.$el.removeClass('step-wizard-nav');
					this.delegateEvents(_.extend({}, this.baseEvents, {}));
				}
				this.render();
			}
		});
		return StepWizardView;
	}
);
