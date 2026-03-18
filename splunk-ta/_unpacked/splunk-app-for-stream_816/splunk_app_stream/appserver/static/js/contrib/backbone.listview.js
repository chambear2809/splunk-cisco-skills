(function(root, factory) {
    // Set up Backbone-associations appropriately for the environment. Start with AMD.
    if (typeof define === 'function' && define.amd) {
        define(['app-js/contrib/underscore', 'app-js/contrib/backbone'], function(_, Backbone) {
            // Export global even in AMD case in case this script is loaded with
            // others that may still expect a global Backbone.
            return factory(root, Backbone, _);
        });

        // Next for Node.js or CommonJS.
    } else if (typeof exports !== 'undefined') {
        var _ = require('underscore'),
            Backbone = require('backbone');
        factory(root, Backbone, _);
        if (typeof module !== 'undefined' && module.exports) {
            module.exports = Backbone;
        }
        exports = Backbone;

        // Finally, as a browser global.
    } else {
        factory(root, root.Backbone, root._);
    }

}(this, function(root, Backbone, _) {
  'use strict';
  var List = Backbone.View.extend({
    className: 'list',

    constructor: function ListView(options) {
      options = options || {};

      this.setupListView(options);
      //this.setupListeners();
      //super call - default Backbone magic
      Backbone.View.call(this, options);
    },

    setupListView: function(options) {
      _.defaults(options, {
        //if no itemView is defined - use backbone default 
        itemView: Backbone.View,
        //if no collection is defined - setup a empty one
        collection: new Backbone.Collection()
      });
      this.items = [];
      this.itemView = options.itemView;
      this.collection = options.collection;
    },

    setupListeners: function() {
      this.listenTo(this.collection, 'add', this.addSingleItem, this);
      this.listenTo(this.collection, 'reset', this.addAll, this);
      this.listenTo(this.collection, 'remove', this.removeSingleItem, this);
    },

    render: function() {
      this.addAll();
      return this;
    },

    addAll: function() {
      //remove previous items if present
      this.removeAllItems();

      //reinit all listeners
      this.setupListeners();
      //add new items
      this.collection.each(function(model) {
        this.addSingleItem(model);
      }, this);
    },

    addSingleItem: function(model) {
      var viewItem = new this.itemView({
        model: model
      });
      this.items.push(viewItem);
      this.addListItemListeners(viewItem);

      viewItem.render();
      this.$el.append(viewItem.el);
      return viewItem;
    },

    removeSingleItem: function(model) {
      var view = this.getViewByModel(model);
      this.removeSingleView(view);
    },

    removeSingleView: function(view) {
      var index;
      //remove listeners
      this.stopListening(view);

      if (view) {
        this.stopListening(view.model);
        view.remove();
        index = this.items.indexOf(view);
        //remove view from items
        this.items.splice(index, 1);
      }
    },

    //propagate list item events through parent list view
    //propagates the single listview and any additional parameters to the listview
    addListItemListeners: function(view) {
      this.listenTo(view, 'all', function() {
        var eventName = 'item:' + arguments[0];
        var params = _.toArray(arguments);
        params.splice(0,1);
        params.unshift(eventName, view);
        this.trigger.apply(this, params);
      });

      this.listenTo(view.model, 'change', function() {
        view.render();
      });
    },

    getViewByModel: function(model) {
      return _.find(this.items, function(item, index) {
        return item.model===model;
      });
    },

    removeAllItems: function() {
      this.collection.each(function(model) {
        this.removeSingleItem(model);
      }, this);
    },

    remove: function() {
      //do the default Backbone remove logic 
      Backbone.View.prototype.remove.call(this, arguments);
      //extra remove our items - one by one
      this.removeAllItems();
    }
  });

  Backbone.ListView = List;

  return List;
}));
