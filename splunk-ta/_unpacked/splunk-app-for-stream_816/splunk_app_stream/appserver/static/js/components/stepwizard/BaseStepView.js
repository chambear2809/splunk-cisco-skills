define([
		"app-js/contrib/underscore",
		"app-js/contrib/backbone",
		"@splunk/ui-utils/i18n"
	],
	function(
		_,
		Backbone,
		Inter
	) {
		/**
		 * This is a base prototype for step views that are brought to life by 
		 * the StepWizardView
		 * @constructor
		 * @module app-components/stepwizard/BaseStepView
		 *
		 *
		 * @event stepforward
		 * @param {BaseStepView} step The step requesting the step forward
		 *
		 * @event customerror
		 * @param {BaseStepView} step The step issuing the error
		 * @param {String} errorMsg The error message
		 *
		 * @event clearerror
		 * @param {BaseStepView} step The step issuing the request
		 */
		var BaseStepView = Backbone.View.extend({
			//
			// Backbone Methods and Property Overloads
			//
			tagName: "div",
			
			className: "step-wizard-step",
			
			/**
			 * Initializes the properties needed for the StepWizardView to use
			 * this View as a step
			 * @param options {Object} initialization options, as indicated below in detail
			 * @param options.value {String} the value to set on the control model when the active step changes
			 */
			initialize: function(options) {
				options = options || {};
				this.value = options.value || this.cid;
				return this;
			},
			
			//
			// Step View Methods and Properties
			//
			/**
			 * whether to show the previous button, optional, defaults to true
			 * @type {Boolean}
			 * @public
			 */
			showPreviousButton: true,
			
			/**
			 * whether to show the next button, optional, defaults to true
			 * @type {Boolean}
			 * @public
			 */
			showNextButton: true,
			
			/**
			 * the label to the show in the previous button (not including the '<' icon), optional, defaults to ''
			 * @type {String}
			 * @public
			 */
			previousLabel: '',
			
			/**
			 * the label to the show in the next button (not including the '>' icon), optional, defaults to 'Save & Next'
			 * @type {String}
			 * @public
			 */
			nextLabel: Inter.gettext('Save & Next'),

			/**
			 * the label to the show in the save button, optional, defaults to 'Save & Exit'
			 * @type {String}
			 * @public
			 */
			saveLabel: Inter.gettext('Save & Exit'),

			/**
			 * whether the step is currently enabled, optional, defaults to true
			 * honestly there may be bugs with this option, seems to have a sketchy relationship with visible
			 * @type {Boolean}
			 * @public
			 */
			enabled: true,
			
			/**
			 * whether the step is currently visible, optional, defaults to true
			 * honestly there may be bugs with this option, seems to have a sketchy relationship with enabled
			 * @type {Boolean}
			 * @public
			 */
			visible: true,
			
			/**
			 * the label to display to the user for the step
			 * @type {String}
			 * @public
			 */
			label: Inter.gettext('Step'),

			/**
			 * the value to lookup the step
			 * @type {String}
			 * @public
			 */
			value: '',

			/**
			 * Event dispatcher to allow for the step to trigger events on parent view
			 * @type {Backbone.Events}
			 */
			dispatcher: null,

			/**
			 * This method is run when a step view is made the current active 
			 * step.
			 * @returns {BaseStepView} this
			 * @public
			 */
			activate: function() {
				return this;
			},
			
			/**
			 * This method is run when a step view is about to be removed from 
			 * being the active step.
			 * @returns {BaseStepView} this
			 * @public
			 */
			deactivate: function() {
				return this;
			},
			
			/**
			 * This method is run to determine if this step can be deactivated 
			 * and changed to the nextStep (which could be behind it). If needed, 
			 * the step that is about to be activated is passed in.
			 * @param {BaseStepView} [nextStep], the step we are trying to switch to.
			 * @returns {$.Deferred} validation status promise, if resolved
			 * @public
			 */
			validate: function(nextStep) {
				throw("Extenders of BaseStepView MUST overload the validate method");
			},

			/**
			 * Save the current state of this step.
			 * This will be called when 'Next' is pressed and at the end when 'Save' is pressed
			 * @param {Boolean} [stepBack] - If true this is called when stepping back
			 * @returns {$.Deferred} save status promise
			 */
			save: function(stepBack) {
				throw("Extenders of BaseStepView MUST overload the save method");
			},

			setEventDispatcher: function(dispatcher) {
				this.dispatcher = dispatcher;
			},
			/**
			 * Call from the step to request stepping the wizard forward.
			 * Validation/Save logic will still occur
			 */
			stepForward: function() {
				if (this.dispatcher) {
					this.dispatcher.trigger('stepforward', this);
				}
			},
			/**
			 *
			 * @param {String} errorMsg
			 */
			showErrorMessage: function(errorMsg) {
				if (this.dispatcher) {
					this.dispatcher.trigger('customerror', this, errorMsg);
				}
			},

			clearErrorMessage: function() {
				if (this.dispatcher) {
					this.dispatcher.trigger('clearerror', this);
				}
			}

		});
		return BaseStepView;
	}
);
