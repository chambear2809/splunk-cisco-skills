#!/usr/bin/env ruby
# frozen_string_literal: true

require "json"
require "optparse"
require "yaml"

options = {}

parser = OptionParser.new do |opts|
  opts.banner = "Usage: spec_to_json.rb --spec PATH --output PATH"
  opts.on("--spec PATH", "Input YAML or JSON spec") { |value| options[:spec] = value }
  opts.on("--output PATH", "Output JSON path") { |value| options[:output] = value }
end

parser.parse!

if options[:spec].to_s.empty? || options[:output].to_s.empty?
  warn parser.to_s
  exit 1
end

input_path = File.expand_path(options[:spec])
output_path = File.expand_path(options[:output])
raw = File.read(input_path, encoding: "UTF-8")

payload =
  if File.extname(input_path).downcase == ".json"
    JSON.parse(raw)
  else
    YAML.safe_load(raw, aliases: true)
  end

File.write(output_path, JSON.pretty_generate(payload) + "\n")

